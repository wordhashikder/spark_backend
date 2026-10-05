"""Back-office use cases: moderating installers and reviews, browsing quotes and messages."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.enums import AccreditationScheme, InstallerStatus, ReviewStatus
from app.core.exceptions import NotFoundError
from app.models import ContactMessage, Installer, QuoteRequest, Review
from app.models.base import utcnow
from app.schemas.admin import AdminInstallerUpdate
from app.services import email as emails
from app.services import reviews
from app.services.email import Email

_INSTALLER_DETAILS = (
    joinedload(Installer.user),
    joinedload(Installer.location),
    selectinload(Installer.accreditations),
)


async def list_installers(
    session: AsyncSession, *, status: InstallerStatus | None, offset: int, limit: int
) -> tuple[list[Installer], int]:
    filters = [Installer.status == status] if status else []
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
        if data.status is InstallerStatus.APPROVED:
            installer.approved_at = utcnow()
            outbox.append(emails.installer_approved(installer, installer.user.email))
        elif data.status is InstallerStatus.REJECTED:
            outbox.append(emails.installer_rejected(installer, installer.user.email))
    if data.plan is not None:
        installer.plan = data.plan
    if data.is_featured is not None:
        installer.is_featured = data.is_featured

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
    session: AsyncSession, *, offset: int, limit: int
) -> tuple[list[QuoteRequest], int]:
    total = await session.scalar(select(func.count()).select_from(QuoteRequest))
    quotes = await session.scalars(
        select(QuoteRequest)
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
