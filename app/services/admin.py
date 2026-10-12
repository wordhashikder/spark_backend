"""Back-office use cases: installers (moderation, adding, editing), reviews, quote requests
(progress, choosing installers for held requests) and the platform's configuration status."""

import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.config import Settings
from app.core.enums import (
    AccreditationScheme,
    InstallerSource,
    InstallerStatus,
    Plan,
    QuoteStatus,
    ReviewStatus,
)
from app.core.exceptions import ConflictError, FieldValidationError, NotFoundError
from app.models import (
    ContactMessage,
    Installer,
    InstallerAccreditation,
    QuoteMatch,
    QuoteRequest,
    Review,
)
from app.models.base import utcnow
from app.schemas.admin import (
    AdminInstallerCreate,
    AdminInstallerUpdate,
    PlatformStatus,
    QuoteCandidate,
)
from app.services import email as emails
from app.services import installers as installer_service
from app.services import lead_stats, locations, matching, reviews
from app.services.email import Email
from app.services.geo import installer_covers_point, installer_distance_to
from app.services.geocoding import Geocoder

_INSTALLER_DETAILS = (
    joinedload(Installer.user),
    joinedload(Installer.location),
    selectinload(Installer.accreditations),
)


async def list_installers(
    session: AsyncSession,
    *,
    status: InstallerStatus | None,
    offset: int,
    limit: int,
    search: str | None = None,
    source: InstallerSource | None = None,
    claimed: bool | None = None,
    plan: Plan | None = None,
) -> tuple[list[Installer], int]:
    filters: list[ColumnElement[bool]] = []
    if status:
        filters.append(Installer.status == status)
    if source:
        filters.append(Installer.source == source)
    if plan:
        filters.append(Installer.plan == plan)
    if claimed is not None:
        filters.append(Installer.user_id.is_not(None) if claimed else Installer.user_id.is_(None))
    if search and search.strip():
        pattern = f"%{_escape_like(search.strip())}%"
        filters.append(
            or_(
                Installer.business_name.ilike(pattern, escape="\\"),
                Installer.town.ilike(pattern, escape="\\"),
                Installer.base_postcode.ilike(pattern, escape="\\"),
                Installer.contact_email.ilike(pattern, escape="\\"),
                Installer.slug.ilike(pattern, escape="\\"),
            )
        )
    total = await session.scalar(select(func.count()).select_from(Installer).where(*filters))
    installers = await session.scalars(
        select(Installer)
        .where(*filters)
        .options(*_INSTALLER_DETAILS)
        .order_by(Installer.created_at.desc(), Installer.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(installers), total or 0


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def get_installer(session: AsyncSession, installer_id: uuid.UUID) -> Installer:
    installer = await session.scalar(
        select(Installer).where(Installer.id == installer_id).options(*_INSTALLER_DETAILS)
    )
    if installer is None:
        raise NotFoundError("Installer not found.")
    return installer


async def _get_installer(session: AsyncSession, installer_id: uuid.UUID) -> Installer:
    installer = await session.scalar(
        select(Installer)
        .where(Installer.id == installer_id)
        .options(*_INSTALLER_DETAILS)
        .with_for_update(of=Installer)
    )
    if installer is None:
        raise NotFoundError("Installer not found.")
    return installer


async def update_installer(
    session: AsyncSession,
    installer_id: uuid.UUID,
    data: AdminInstallerUpdate,
    geocoder: Geocoder,
) -> tuple[Installer, list[Email]]:
    """Change the fields sent; approving or rejecting emails the installer.

    A new postcode moves the listing's base (and its town page) like the installer's own
    profile edit does.
    """
    installer = await _get_installer(session, installer_id)
    outbox: list[Email] = []

    if data.status is not None and data.status is not installer.status:
        installer.status = data.status
        # Listings without an account have no one to tell.
        if data.status is InstallerStatus.APPROVED:
            installer.approved_at = utcnow()
            if installer.user is not None:
                outbox.append(emails.installer_approved(installer, installer.user.email))
        elif data.status is InstallerStatus.REJECTED and installer.user is not None:
            outbox.append(emails.installer_rejected(installer, installer.user.email))
    if data.plan is not None:
        installer.plan = data.plan
    if data.is_featured is not None:
        installer.is_featured = data.is_featured
    for field in ("contact_email", "contact_name", "description"):
        if field in data.model_fields_set:
            setattr(
                installer, field, getattr(data, field) or ("" if field == "contact_name" else None)
            )
    if data.business_name is not None:
        installer.business_name = data.business_name
    if data.phone is not None:
        installer.phone = data.phone
    if data.coverage_radius_miles is not None:
        installer.coverage_radius_miles = data.coverage_radius_miles
    if data.base_postcode is not None and data.base_postcode != installer.base_postcode:
        await _place(session, installer, data.base_postcode, geocoder)

    await session.commit()
    return await get_installer(session, installer.id), outbox


async def create_installer(
    session: AsyncSession, data: AdminInstallerCreate, geocoder: Geocoder
) -> Installer:
    """A listing added by the team. It has no account: the business can claim it later."""
    if await find_duplicate(session, data.business_name, data.contact_email):
        raise FieldValidationError(
            {"business_name": "A listing with this name or email already exists."}
        )
    installer = await build_listing(session, data, geocoder)
    await session.commit()
    return await get_installer(session, installer.id)


async def find_duplicate(session: AsyncSession, business_name: str, email: str) -> bool:
    """A listing with this business name or email is already on the platform."""
    found = await session.scalar(
        select(Installer.id)
        .where(
            or_(
                func.lower(Installer.business_name) == business_name.lower(),
                func.lower(Installer.contact_email) == email.lower(),
            )
        )
        .limit(1)
    )
    return found is not None


async def build_listing(
    session: AsyncSession, data: AdminInstallerCreate, geocoder: Geocoder
) -> Installer:
    """Add (without committing) an unclaimed listing placed at its postcode."""
    installer = Installer(
        slug=await installer_service.unique_slug(session, data.business_name),
        business_name=data.business_name,
        contact_name=data.contact_name or "",
        contact_email=data.contact_email,
        phone=data.phone,
        description=data.description,
        coverage_radius_miles=data.coverage_radius_miles,
        services=[service.value for service in data.services],
        status=data.status,
        plan=data.plan,
        approved_at=utcnow() if data.status is InstallerStatus.APPROVED else None,
        source=InstallerSource.IMPORTED,
        accreditations=[
            InstallerAccreditation(scheme=scheme, verified=False)
            for scheme in dict.fromkeys(data.accreditations)
        ],
    )
    await _place(session, installer, data.base_postcode, geocoder)
    installer.areas_covered = [installer.town]
    session.add(installer)
    await session.flush()
    return installer


async def _place(
    session: AsyncSession, installer: Installer, postcode: str, geocoder: Geocoder
) -> None:
    """Base the listing at a postcode: its coordinates, town and nearest town page."""
    place = await installer_service.geocode_or_field_error(geocoder, postcode, "base_postcode")
    location = await locations.nearest(session, place.latitude, place.longitude)
    installer.base_postcode = place.postcode
    installer.latitude = place.latitude
    installer.longitude = place.longitude
    installer.town = place.district or location.name
    installer.location = location


async def set_accreditation_verified(
    session: AsyncSession, installer_id: uuid.UUID, scheme: AccreditationScheme, verified: bool
) -> Installer:
    installer = await _get_installer(session, installer_id)
    accreditation = next((item for item in installer.accreditations if item.scheme is scheme), None)
    if accreditation is None:
        raise NotFoundError("The installer does not list this accreditation.")
    accreditation.verified = verified
    await session.commit()
    return installer


async def list_reviews(
    session: AsyncSession, *, status: ReviewStatus | None, offset: int, limit: int
) -> tuple[list[Review], int]:
    filters = [Review.status == status] if status else []
    total = await session.scalar(select(func.count()).select_from(Review).where(*filters))
    found = await session.scalars(
        select(Review)
        .where(*filters)
        .options(joinedload(Review.installer))
        .order_by(Review.created_at.desc(), Review.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(found), total or 0


async def moderate_review(
    session: AsyncSession, review_id: uuid.UUID, status: ReviewStatus
) -> Review:
    """Publish or reject a review and bring the installer's rating summary up to date."""
    review = await session.scalar(
        select(Review)
        .where(Review.id == review_id)
        .options(joinedload(Review.installer))
        .with_for_update(of=Review)
    )
    if review is None:
        raise NotFoundError("Review not found.")
    if status is not review.status:
        review.status = status
        if status is ReviewStatus.PUBLISHED:
            review.published_at = utcnow()
        await session.flush()
        await reviews.recompute_rating(session, review.installer_id)
    await session.commit()
    return review


async def list_quotes(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    status: QuoteStatus | None = None,
    stage: lead_stats.Stage | None = None,
    search: str | None = None,
) -> tuple[list[tuple[QuoteRequest, int, int, str]], int]:
    """Quote requests, newest first, each with (installers matched, quotes sent, stage)."""
    filters: list[ColumnElement[bool]] = []
    if status:
        filters.append(QuoteRequest.status == status)
    if stage:
        filters.append(lead_stats.stage_filter(stage))
    if search and search.strip():
        pattern = f"%{_escape_like(search.strip())}%"
        filters.append(
            or_(
                QuoteRequest.reference.ilike(pattern, escape="\\"),
                QuoteRequest.postcode.ilike(pattern, escape="\\"),
                QuoteRequest.email.ilike(pattern, escape="\\"),
                QuoteRequest.first_name.ilike(pattern, escape="\\"),
                QuoteRequest.district.ilike(pattern, escape="\\"),
            )
        )
    total = await session.scalar(select(func.count()).select_from(QuoteRequest).where(*filters))
    rows = await session.execute(
        select(
            QuoteRequest,
            lead_stats.installers_matched(),
            lead_stats.quotes_sent(),
            lead_stats.stage(),
        )
        .where(*filters)
        .order_by(QuoteRequest.created_at.desc(), QuoteRequest.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return [(quote, matched or 0, sent or 0, stage) for quote, matched, sent, stage in rows], (
        total or 0
    )


async def stage_counts(session: AsyncSession) -> dict[str, int]:
    """How many requests are at each stage (the Leads & Quotes filter chips)."""
    stages = select(lead_stats.stage().label("stage")).subquery()
    rows = await session.execute(select(stages.c.stage, func.count()).group_by(stages.c.stage))
    counts = {"open": 0, "awaiting": 0, "closed": 0}
    for stage, count in rows:
        counts[stage] = count
    counts["all"] = sum(counts.values())
    counts["held"] = (
        await session.scalar(
            select(func.count())
            .select_from(QuoteRequest)
            .where(QuoteRequest.status == QuoteStatus.NEW)
        )
        or 0
    )
    return counts


async def list_contact_messages(
    session: AsyncSession, *, offset: int, limit: int
) -> tuple[list[ContactMessage], int]:
    total = await session.scalar(select(func.count()).select_from(ContactMessage))
    messages = await session.scalars(
        select(ContactMessage)
        .order_by(ContactMessage.created_at.desc(), ContactMessage.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(messages), total or 0


async def quote_matches(session: AsyncSession, quote_id: uuid.UUID) -> list[QuoteMatch]:
    """The installers a quote request was sent to, with their progress."""
    if await session.get(QuoteRequest, quote_id) is None:
        raise NotFoundError("Quote request not found.")
    return list(
        await session.scalars(
            select(QuoteMatch)
            .where(QuoteMatch.quote_request_id == quote_id)
            .options(joinedload(QuoteMatch.installer))
            .order_by(QuoteMatch.created_at)
        )
    )


async def quote_candidates(session: AsyncSession, quote_id: uuid.UUID) -> list[QuoteCandidate]:
    """Installers the team can send a request to: lead-receiving installers, nearest first.

    Those whose coverage includes the address come first; the rest are listed by distance
    so the team can widen the search for an area nobody covers.
    """
    quote = await _get_quote(session, quote_id)
    already = set(
        await session.scalars(
            select(QuoteMatch.installer_id).where(QuoteMatch.quote_request_id == quote.id)
        )
    )
    if quote.latitude is None or quote.longitude is None:
        found = await session.scalars(
            select(Installer)
            .where(*matching.receives_leads())
            .order_by(Installer.business_name)
            .limit(_CANDIDATES)
        )
        return [_candidate(installer, None, False, installer.id in already) for installer in found]
    distance = installer_distance_to(quote.latitude, quote.longitude)
    covers = installer_covers_point(quote.latitude, quote.longitude)
    rows = await session.execute(
        select(Installer, distance, covers)
        .where(*matching.receives_leads())
        .order_by(covers.desc(), distance, Installer.id)
        .limit(_CANDIDATES)
    )
    return [
        _candidate(installer, float(miles), bool(inside), installer.id in already)
        for installer, miles, inside in rows
    ]


_CANDIDATES = 25


def _candidate(
    installer: Installer, miles: float | None, covers: bool, matched: bool
) -> QuoteCandidate:
    return QuoteCandidate(
        id=installer.id,
        slug=installer.slug,
        business_name=installer.business_name,
        town=installer.town,
        plan=installer.plan,
        rating_avg=None if installer.rating_avg is None else float(installer.rating_avg),
        review_count=installer.review_count,
        distance_miles=None if miles is None else round(miles, 1),
        covers_address=covers,
        already_matched=matched,
    )


async def assign_quote(
    session: AsyncSession,
    quote_id: uuid.UUID,
    installer_ids: Sequence[uuid.UUID],
    *,
    max_installers: int,
) -> tuple[list[QuoteMatch], list[Email]]:
    """Send a request to installers the team picked (held or unmatched requests, or to add
    one more). Each installer gets the usual new-lead email; the homeowner is told who."""
    quote = await _get_quote(session, quote_id, lock=True)
    already = set(
        await session.scalars(
            select(QuoteMatch.installer_id).where(QuoteMatch.quote_request_id == quote.id)
        )
    )
    wanted = [
        installer_id for installer_id in dict.fromkeys(installer_ids) if installer_id not in already
    ]
    if not wanted:
        raise ConflictError("These installers already have this request.", code="already_matched")
    if len(already) + len(wanted) > max_installers:
        raise FieldValidationError(
            {
                "installer_ids": (
                    f"A request goes to at most {max_installers} installers "
                    f"({len(already)} already have it)."
                )
            }
        )
    found = list(
        await session.scalars(
            select(Installer)
            .where(Installer.id.in_(wanted), *matching.receives_leads())
            .options(joinedload(Installer.user))
        )
    )
    if len(found) != len(wanted):
        raise FieldValidationError(
            {"installer_ids": "Choose approved installers whose plan includes leads."}
        )
    added = [QuoteMatch(quote_request=quote, installer=installer) for installer in found]
    session.add_all(added)
    quote.status = QuoteStatus.MATCHED
    await session.commit()
    outbox: list[Email] = [
        emails.new_lead(quote, installer, installer.user.email)
        for installer in found
        if installer.user is not None
    ]
    outbox.append(emails.quote_shared(quote, [installer.business_name for installer in found]))
    return await quote_matches(session, quote.id), outbox


async def get_quote(session: AsyncSession, quote_id: uuid.UUID) -> QuoteRequest:
    return await _get_quote(session, quote_id)


async def _get_quote(
    session: AsyncSession, quote_id: uuid.UUID, *, lock: bool = False
) -> QuoteRequest:
    statement = select(QuoteRequest).where(QuoteRequest.id == quote_id)
    if lock:
        statement = statement.with_for_update()
    quote = await session.scalar(statement)
    if quote is None:
        raise NotFoundError("Quote request not found.")
    return quote


def platform_status(settings: Settings) -> PlatformStatus:
    """What is configured on the server (never the secrets themselves)."""
    return PlatformStatus(
        environment=settings.environment,
        frontend_url=settings.frontend_url,
        dashboard_url=settings.dashboard_url,
        email_configured=settings.smtp_configured,
        image_uploads_configured=settings.cloudinary_configured,
        payments_configured=settings.stripe_configured,
        sms_configured=False,
        showcase_enabled=settings.seed_showcase,
    )
