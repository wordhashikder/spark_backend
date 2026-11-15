"""Quote requests: creation, matching and the emails that follow."""

import logging
import secrets
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import get_settings
from app.core.enums import QuoteStatus
from app.models import Installer, QuoteMatch, QuoteRequest
from app.models.base import utcnow
from app.schemas.quote import QuoteCreate, QuoteCreated
from app.services import customers, installers, matching
from app.services import email as emails
from app.services.email import Email
from app.services.geocoding import GeocodedPostcode, Geocoder, GeocodingUnavailableError
from app.services.platform import LeadMatching

logger = logging.getLogger(__name__)

REFERENCE_PREFIX = "PAS-"
# No 0/O, 1/I/L: references get read out over the phone.
_REFERENCE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_REFERENCE_LENGTH = 6
_REFERENCE_ATTEMPTS = 5


def _random_reference() -> str:
    code = "".join(secrets.choice(_REFERENCE_ALPHABET) for _ in range(_REFERENCE_LENGTH))
    return f"{REFERENCE_PREFIX}{code}"


async def _unused_reference(session: AsyncSession) -> str:
    for _ in range(_REFERENCE_ATTEMPTS):
        reference = _random_reference()
        taken = await session.scalar(
            select(QuoteRequest.id).where(QuoteRequest.reference == reference)
        )
        if taken is None:
            return reference
    raise RuntimeError("Could not generate an unused quote reference")


def decoy_response(data: QuoteCreate) -> QuoteCreated:
    """What a bot that filled in the honeypot sees: a normal-looking success, nothing stored."""
    return QuoteCreated(reference=_random_reference(), postcode=data.postcode, matched_installers=0)


async def _geocode(geocoder: Geocoder, postcode: str) -> GeocodedPostcode | None:
    """Geocode for matching. `None` means the lookup service is down (an unknown postcode
    raises, as before): the request is kept and matched later by `quote_recovery`."""
    try:
        return await installers.geocode_or_field_error(geocoder, postcode, "postcode")
    except GeocodingUnavailableError:
        logger.warning("Geocoding unavailable; quote for %s waits for the lookup", postcode)
        return None


async def match_stored_quote(
    session: AsyncSession,
    quote: QuoteRequest,
    target: Installer | None,
    rules: LeadMatching,
) -> tuple[list[QuoteMatch], bool]:
    """Match a request that has its coordinates: create the leads and set the status.

    Used for a new request and, later, for one that was waiting for the lookup service.
    Returns the leads and whether the request is held for the team (automatic matching off).
    """
    if quote.latitude is None or quote.longitude is None:
        raise ValueError("The request has no coordinates to match on.")
    matched = await matching.match_installers(
        session,
        latitude=quote.latitude,
        longitude=quote.longitude,
        target=target,
        limit=None if rules.automatic else 1,
        nearby=rules.automatic,
    )
    leads = [
        QuoteMatch(id=uuid.uuid7(), quote_request=quote, installer=installer)
        for installer in matched
    ]
    session.add_all(leads)
    held = not rules.automatic and not matched
    if matched:
        quote.status = QuoteStatus.MATCHED
    else:
        quote.status = QuoteStatus.NEW if held else QuoteStatus.UNMATCHED
    return leads, held


def lead_emails(
    quote: QuoteRequest, leads: Sequence[QuoteMatch], *, held: bool, slots: int
) -> list[Email]:
    """The emails that follow matching: each installer's new lead, or the team's alert when
    nobody was matched (or the request is held for them)."""
    outbox = [
        emails.new_lead(quote, lead.installer, lead.installer.user.email, lead.id, slots)
        for lead in leads
    ]
    if not leads:
        outbox.append(emails.quote_unmatched(quote, held=held))
    return outbox


async def create_quote(
    session: AsyncSession,
    data: QuoteCreate,
    geocoder: Geocoder,
    client_ip: str,
    rules: LeadMatching | None = None,
) -> tuple[QuoteCreated, list[Email]]:
    """Store a quote request, match it to installers and return the emails to send.

    Every eligible installer covering the address is told (no cap); only the first
    `rules.max_installers` to respond may quote. With automatic matching off (Settings), the
    request is held for the team to choose its installers; only an installer the homeowner
    asked for by name receives it at once.

    If the postcode lookup is down, the request is stored as `PENDING_LOCATION`, not as
    unmatched, and `quote_recovery` matches it when the service answers again. The homeowner
    sees and receives exactly what they always do (nothing reveals the outage); only the team
    is alerted, and can choose installers themselves meanwhile.
    """
    rules = rules or LeadMatching(max_installers=get_settings().max_quote_matches)
    place = await _geocode(geocoder, data.postcode)
    target = (
        await matching.direct_quote_target(session, data.installer_slug)
        if data.installer_slug
        else None
    )
    customer = await customers.get_or_create(session, data.email, data.first_name, data.phone)
    quote = QuoteRequest(
        customer_id=customer.id,
        reference=await _unused_reference(session),
        postcode=place.postcode if place else data.postcode,
        latitude=place.latitude if place else None,
        longitude=place.longitude if place else None,
        district=place.district if place else None,
        region=place.region if place else None,
        installation_type=data.installation_type,
        charger_location=data.charger_location,
        existing_charger=data.existing_charger,
        charger_followup=data.charger_followup,
        fuse_box_distance=data.fuse_box_distance,
        vehicle=data.vehicle,
        vehicle_undecided=data.vehicle_undecided,
        timing=data.timing,
        notes=data.notes,
        first_name=data.first_name,
        email=data.email,
        phone=data.phone,
        consent_at=utcnow(),
        target_installer_id=target.id if target else None,
        ip_hash=security.hash_ip(client_ip),
    )
    session.add(quote)

    pending = place is None
    leads: list[QuoteMatch] = []
    held = False
    if pending:
        quote.status = QuoteStatus.PENDING_LOCATION
    else:
        leads, held = await match_stored_quote(session, quote, target, rules)
    link = customers.link_url(await customers.issue_link(session, customer))
    await session.commit()

    outbox = [
        emails.quote_confirmation(
            quote,
            [lead.installer.business_name for lead in leads],
            held=held,
            link=link,
        ),
    ]
    if pending:
        # Only the team hears about the outage; the homeowner gets the usual confirmation.
        outbox.append(emails.quote_awaiting_location(quote))
    else:
        outbox += lead_emails(quote, leads, held=held, slots=rules.max_installers)
    return (
        QuoteCreated(
            reference=quote.reference,
            postcode=quote.postcode,
            matched_installers=len(leads),
            held=held,
        ),
        outbox,
    )
