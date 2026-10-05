"""Quote requests: creation, matching and the emails that follow."""

import logging
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import get_settings
from app.core.enums import QuoteStatus
from app.models import QuoteMatch, QuoteRequest
from app.models.base import utcnow
from app.schemas.quote import QuoteCreate, QuoteCreated
from app.services import email as emails
from app.services import installers, matching
from app.services.email import Email
from app.services.geocoding import GeocodedPostcode, Geocoder, GeocodingUnavailableError

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
    """Geocode for matching; an outage is tolerated so the customer's request is never lost."""
    try:
        return await installers.geocode_or_field_error(geocoder, postcode, "postcode")
    except GeocodingUnavailableError:
        logger.warning("Geocoding unavailable; storing quote for %s unmatched", postcode)
        return None


async def create_quote(
    session: AsyncSession, data: QuoteCreate, geocoder: Geocoder, client_ip: str
) -> tuple[QuoteCreated, list[Email]]:
    """Store a quote request, match it to installers and return the emails to send."""
    place = await _geocode(geocoder, data.postcode)
    target = (
        await matching.direct_quote_target(session, data.installer_slug)
        if data.installer_slug
        else None
    )
    quote = QuoteRequest(
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

    matched = (
        await matching.match_installers(
            session,
            latitude=place.latitude,
            longitude=place.longitude,
            target=target,
            limit=get_settings().max_quote_matches,
        )
        if place
        else []
    )
    session.add_all(QuoteMatch(quote_request=quote, installer=installer) for installer in matched)
    quote.status = QuoteStatus.MATCHED if matched else QuoteStatus.UNMATCHED
    await session.commit()

    outbox = [
        emails.quote_confirmation(quote, [installer.business_name for installer in matched]),
        *(emails.new_lead(quote, installer, installer.user.email) for installer in matched),
    ]
    if not matched:
        outbox.append(emails.quote_unmatched(quote))
    return (
        QuoteCreated(
            reference=quote.reference, postcode=quote.postcode, matched_installers=len(matched)
        ),
        outbox,
    )
