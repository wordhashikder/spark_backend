"""Back-office use cases: moderating installers and reviews, browsing quotes and messages."""

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import ColumnElement, Date, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.config import Settings
from app.core.enums import (
    AccreditationScheme,
    BlogPostStatus,
    InstallerSource,
    InstallerStatus,
    OfferStatus,
    Plan,
    QuoteStatus,
    ReviewStatus,
    Role,
)
from app.core.exceptions import NotFoundError
from app.models import (
    BlogPost,
    ContactMessage,
    Conversation,
    Installer,
    InstallerEnquiry,
    Location,
    Offer,
    QuoteMatch,
    QuoteRequest,
    Review,
    User,
)
from app.models.base import utcnow
from app.schemas.admin import (
    AdminInstallerUpdate,
    AdminOverview,
    CountByKey,
    DailyCount,
    PlatformInfo,
)
from app.services import email as emails
from app.services import reviews
from app.services.email import Email

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
    session: AsyncSession, installer_id: uuid.UUID, data: AdminInstallerUpdate
) -> tuple[Installer, list[Email]]:
    """Change status, plan or featuring; approving or rejecting emails the installer."""
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
    if "contact_email" in data.model_fields_set:
        installer.contact_email = data.contact_email

    await session.commit()
    return installer, outbox


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
    search: str | None = None,
) -> tuple[list[QuoteRequest], int]:
    filters: list[ColumnElement[bool]] = []
    if status:
        filters.append(QuoteRequest.status == status)
    if search and search.strip():
        pattern = f"%{_escape_like(search.strip())}%"
        filters.append(
            or_(
                QuoteRequest.reference.ilike(pattern, escape="\\"),
                QuoteRequest.postcode.ilike(pattern, escape="\\"),
                QuoteRequest.email.ilike(pattern, escape="\\"),
                QuoteRequest.first_name.ilike(pattern, escape="\\"),
            )
        )
    total = await session.scalar(select(func.count()).select_from(QuoteRequest).where(*filters))
    quotes = await session.scalars(
        select(QuoteRequest)
        .where(*filters)
        .order_by(QuoteRequest.created_at.desc(), QuoteRequest.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(quotes), total or 0


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


async def _counts(
    session: AsyncSession, column: ColumnElement, *filters: ColumnElement[bool]
) -> list[CountByKey]:
    rows = await session.execute(select(column, func.count()).where(*filters).group_by(column))
    return [CountByKey(key=str(key), count=count) for key, count in rows]


async def _count(session: AsyncSession, model: type, *filters: ColumnElement[bool]) -> int:
    return await session.scalar(select(func.count()).select_from(model).where(*filters)) or 0


async def overview(session: AsyncSession, *, days: int = 30) -> AdminOverview:
    """The back-office dashboard: headline numbers and the last `days` days of activity."""
    since = utcnow() - timedelta(days=days)
    day = cast(QuoteRequest.created_at, Date)
    daily = await session.execute(
        select(day, func.count())
        .where(QuoteRequest.created_at >= since)
        .group_by(day)
        .order_by(day)
    )
    enquiry_day = cast(InstallerEnquiry.created_at, Date)
    daily_enquiries = await session.execute(
        select(enquiry_day, func.count())
        .where(InstallerEnquiry.created_at >= since)
        .group_by(enquiry_day)
        .order_by(enquiry_day)
    )
    accepted_value = await session.scalar(
        select(func.coalesce(func.sum(Offer.amount), 0)).where(Offer.status == OfferStatus.ACCEPTED)
    )
    return AdminOverview(
        period_days=days,
        installers_total=await _count(session, Installer),
        installers_by_status=await _counts(session, Installer.status),
        installers_by_plan=await _counts(
            session, Installer.plan, Installer.status == InstallerStatus.APPROVED
        ),
        installers_by_source=await _counts(session, Installer.source),
        installers_claimed=await _count(session, Installer, Installer.user_id.is_not(None)),
        installers_pending=await _count(
            session, Installer, Installer.status == InstallerStatus.PENDING
        ),
        quote_requests_total=await _count(session, QuoteRequest),
        quote_requests_recent=await _count(session, QuoteRequest, QuoteRequest.created_at >= since),
        quote_requests_by_status=await _counts(session, QuoteRequest.status),
        leads_total=await _count(session, QuoteMatch),
        enquiries_total=await _count(session, InstallerEnquiry),
        enquiries_recent=await _count(
            session, InstallerEnquiry, InstallerEnquiry.created_at >= since
        ),
        enquiries_for_team=await _count(
            session, InstallerEnquiry, InstallerEnquiry.sent_to_installer.is_(False)
        ),
        conversations_total=await _count(session, Conversation),
        offers_by_status=await _counts(session, Offer.status),
        accepted_quote_value=Decimal(accepted_value or 0),
        reviews_pending=await _count(session, Review, Review.status == ReviewStatus.PENDING),
        reviews_published=await _count(session, Review, Review.status == ReviewStatus.PUBLISHED),
        contact_messages_recent=await _count(
            session, ContactMessage, ContactMessage.created_at >= since
        ),
        blog_published=await _count(session, BlogPost, BlogPost.status == BlogPostStatus.PUBLISHED),
        blog_drafts=await _count(session, BlogPost, BlogPost.status == BlogPostStatus.DRAFT),
        locations_total=await _count(session, Location),
        quote_requests_daily=[DailyCount(day=d, count=c) for d, c in daily],
        enquiries_daily=[DailyCount(day=d, count=c) for d, c in daily_enquiries],
    )


async def platform_info(session: AsyncSession, settings: Settings) -> PlatformInfo:
    admins = await session.scalars(
        select(User.email).where(User.role == Role.ADMIN, User.is_active).order_by(User.email)
    )
    return PlatformInfo(
        environment=settings.environment,
        frontend_url=settings.frontend_url,
        dashboard_url=settings.dashboard_url,
        support_email=settings.support_email,
        email_configured=settings.smtp_configured,
        image_uploads_configured=settings.cloudinary_configured,
        payments_configured=settings.stripe_configured,
        max_quote_matches=settings.max_quote_matches,
        showcase_enabled=not settings.is_production or settings.seed_showcase,
        admins=list(admins),
    )
