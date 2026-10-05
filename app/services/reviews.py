"""Reviews: public listings, invitation-based submission and rating upkeep."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core import security
from app.core.enums import InstallerStatus, ReviewStatus
from app.core.exceptions import InvalidTokenError, NotFoundError
from app.models import Installer, QuoteMatch, Review
from app.schemas.review import ReviewCreate
from app.services import installers

MAX_FEATURED = 20
_FEATURED_MIN_RATING = 4


class InvitationNotFoundError(NotFoundError):
    code = "invalid_token"
    message = "This review link is invalid or has already been used."


async def list_featured(session: AsyncSession, limit: int) -> list[Review]:
    """Recent published reviews rated 4 or 5 of installers that are still listed."""
    reviews = await session.scalars(
        select(Review)
        .join(Installer, Installer.id == Review.installer_id)
        .where(
            Review.status == ReviewStatus.PUBLISHED,
            Review.rating >= _FEATURED_MIN_RATING,
            Installer.status == InstallerStatus.APPROVED,
        )
        .order_by(Review.created_at.desc(), Review.id.desc())
        .limit(min(limit, MAX_FEATURED))
    )
    return list(reviews)


async def list_for_installer(
    session: AsyncSession, slug: str, *, offset: int, limit: int
) -> tuple[list[Review], int]:
    """An approved installer's published reviews, newest first."""
    installer = await installers.get_public(session, slug)
    published = (Review.installer_id == installer.id, Review.status == ReviewStatus.PUBLISHED)
    total = await session.scalar(select(func.count()).select_from(Review).where(*published))
    reviews = await session.scalars(
        select(Review)
        .where(*published)
        .order_by(Review.created_at.desc(), Review.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(reviews), total or 0


async def _open_invitation(session: AsyncSession, token: str) -> QuoteMatch | None:
    """The lead a review invitation points at, unless the token is bad or already used."""
    try:
        quote_match_id = security.decode_review_invite_token(token)
    except security.TokenError:
        return None
    lead = await session.scalar(
        select(QuoteMatch)
        .where(QuoteMatch.id == quote_match_id, QuoteMatch.review_invited_at.is_not(None))
        .options(joinedload(QuoteMatch.installer))
    )
    if lead is None:
        return None
    already_reviewed = await session.scalar(
        select(Review.id).where(Review.quote_match_id == lead.id)
    )
    return None if already_reviewed else lead


async def get_invitation(session: AsyncSession, token: str) -> Installer:
    """The installer a valid, unused invitation is for."""
    lead = await _open_invitation(session, token)
    if lead is None:
        raise InvitationNotFoundError
    return lead.installer


async def submit(session: AsyncSession, data: ReviewCreate) -> None:
    """Store a pending, verified review; each invitation can be used once."""
    lead = await _open_invitation(session, data.token)
    if lead is None:
        raise InvalidTokenError("This review link is invalid or has already been used.")
    session.add(
        Review(
            installer_id=lead.installer_id,
            quote_match_id=lead.id,
            rating=data.rating,
            title=data.title,
            body=data.body,
            author_name=data.author_name,
            author_location=data.author_location,
        )
    )
    try:
        await session.commit()
    except IntegrityError as exc:
        # A concurrent submission with the same invitation won the unique constraint.
        await session.rollback()
        raise InvalidTokenError("This review link is invalid or has already been used.") from exc


async def recompute_rating(session: AsyncSession, installer_id: uuid.UUID) -> None:
    """Refresh an installer's rating summary from its published reviews (caller commits)."""
    installer = await session.get(Installer, installer_id, with_for_update=True)
    if installer is None:
        return
    average, count = (
        await session.execute(
            select(func.round(func.avg(Review.rating), 1), func.count()).where(
                Review.installer_id == installer_id, Review.status == ReviewStatus.PUBLISHED
            )
        )
    ).one()
    installer.rating_avg = average
    installer.review_count = count
