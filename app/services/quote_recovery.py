"""Quote requests that arrived while the postcode lookup (postcodes.io) was down.

Such a request is stored in full with the status `PENDING_LOCATION` (see `quotes.create_quote`):
it is not a verdict on the request, so it is never marked unmatched because of an outage.
This module looks for them regularly and, once the lookup answers, matches them exactly as if
they had just arrived:

- the postcode is known: coordinates are saved and installers are matched and told;
- the postcode is not known (the homeowner mistyped it): the request becomes unmatched and the
  team is told, with the reason;
- the lookup is still down: nothing changes and the next pass tries again.

The homeowner is never told: they get the usual confirmation and see the request under "My
requests" as matching. The team is alerted when the request arrives (`quote_awaiting_location`)
and the request shows under "Waiting for you" (see `lead_stats.waiting_for_team`), so they can
choose installers themselves instead of waiting; once matched the loop leaves it alone.

Every worker runs the loop; `FOR UPDATE SKIP LOCKED` makes each request belong to one of them
at a time, and each is handled in its own transaction, so one failure never affects another.
"""

import asyncio
import logging
import uuid

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.enums import QuoteStatus
from app.models import QuoteRequest
from app.services import matching, platform, quotes
from app.services.email import Email, EmailSender, for_delivery
from app.services.email import quote_unmatched as unmatched_alert
from app.services.geocoding import Geocoder, GeocodingUnavailableError, PostcodeNotFoundError

logger = logging.getLogger(__name__)


async def _recover_next(geocoder: Geocoder, seen: set[uuid.UUID]) -> list[Email] | None:
    """Match the oldest waiting request; `None` when none is left or the lookup is still down.

    Returns the emails to send, already prepared for delivery.
    """
    async with SessionFactory() as session:
        statement = (
            select(QuoteRequest)
            .where(QuoteRequest.status == QuoteStatus.PENDING_LOCATION)
            .order_by(QuoteRequest.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if seen:
            statement = statement.where(QuoteRequest.id.not_in(seen))
        quote = await session.scalar(statement)
        if quote is None:
            return None
        seen.add(quote.id)
        reference = quote.reference  # read now: a rollback expires the object

        try:
            place = await geocoder.lookup(quote.postcode)
        except GeocodingUnavailableError:
            await session.rollback()
            logger.info("Postcode lookup still unavailable; quote %s keeps waiting", reference)
            return None
        except PostcodeNotFoundError:
            quote.status = QuoteStatus.UNMATCHED
            await session.commit()
            logger.info("Quote %s: the postcode is not recognised", reference)
            outbox = [unmatched_alert(quote, postcode_unknown=True)]
        else:
            quote.postcode = place.postcode
            quote.latitude = place.latitude
            quote.longitude = place.longitude
            quote.district = place.district
            quote.region = place.region
            rules = (await platform.load(session)).lead_matching
            target = (
                await matching.installer_by_id(session, quote.target_installer_id)
                if quote.target_installer_id
                else None
            )
            leads, held = await quotes.match_stored_quote(session, quote, target, rules)
            await session.commit()
            logger.info(
                "Quote %s matched after the lookup returned: %d installer(s)",
                reference,
                len(leads),
            )
            outbox = quotes.lead_emails(quote, leads, held=held, slots=rules.max_installers)

        settings = await platform.load(session)
        return [p for email in outbox if (p := for_delivery(email, settings)) is not None]


async def recover_pending(geocoder: Geocoder, sender: EmailSender, *, batch: int) -> int:
    """Match up to `batch` waiting requests; returns how many were dealt with."""
    handled = 0
    seen: set[uuid.UUID] = set()
    for _ in range(batch):
        try:
            outbox = await _recover_next(geocoder, seen)
        except Exception:
            # The request stays waiting (its transaction was rolled back); carry on with the rest.
            logger.exception("Could not match a waiting quote request")
            continue
        if outbox is None:
            break
        handled += 1
        for email in outbox:
            await sender.send(email)
    return handled


async def recover_forever(geocoder: Geocoder, sender: EmailSender) -> None:
    """Retry waiting requests at a steady pace for as long as the application runs."""
    settings = get_settings()
    while True:
        try:
            await recover_pending(geocoder, sender, batch=settings.quote_recovery_batch)
        except Exception:
            logger.exception("Quote recovery pass failed")
        await asyncio.sleep(settings.quote_recovery_interval_seconds)
