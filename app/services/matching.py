"""Matching quote requests to installers by coverage, plan and distance."""

from sqlalchemy import func, nulls_last, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.enums import InstallerStatus
from app.core.plans import LEAD_RECEIVING_PLANS, capabilities_for, sort_rank_expression
from app.models import Installer
from app.services.geo import installer_covers_point, installer_distance_to


def _receives_leads() -> tuple:
    """SQL filters selecting approved installers whose effective plan receives leads.

    A listing nobody has claimed yet has no one to send leads to, whatever its plan.
    """
    return (
        Installer.status == InstallerStatus.APPROVED,
        Installer.plan.in_(LEAD_RECEIVING_PLANS),
        Installer.user_id.is_not(None),
    )


async def count_in_range(session: AsyncSession, latitude: float, longitude: float) -> int:
    """How many lead-receiving installers cover a point."""
    count = await session.scalar(
        select(func.count())
        .select_from(Installer)
        .where(*_receives_leads(), installer_covers_point(latitude, longitude))
    )
    return count or 0


async def direct_quote_target(session: AsyncSession, slug: str) -> Installer | None:
    """The approved installer a customer asked for by name, if it exists."""
    return await session.scalar(
        select(Installer)
        .where(Installer.slug == slug, Installer.status == InstallerStatus.APPROVED)
        .options(joinedload(Installer.user))
    )


async def match_installers(
    session: AsyncSession,
    *,
    latitude: float,
    longitude: float,
    target: Installer | None,
    limit: int,
) -> list[Installer]:
    """Pick the installers to receive a quote request.

    A requested installer that accepts direct quotes always comes first. The rest are
    lead-receiving installers whose coverage circle contains the point, best plan first,
    then nearest, then highest rated.
    """
    matched: list[Installer] = []
    if (
        target is not None
        and target.user_id is not None
        and capabilities_for(target.plan).accepts_direct_quotes
    ):
        matched.append(target)

    remaining = limit - len(matched)
    if remaining > 0:
        nearby = await session.scalars(
            select(Installer)
            .where(
                *_receives_leads(),
                installer_covers_point(latitude, longitude),
                Installer.id.not_in([installer.id for installer in matched]),
            )
            .options(joinedload(Installer.user))
            .order_by(
                sort_rank_expression(Installer.plan).desc(),
                installer_distance_to(latitude, longitude),
                nulls_last(Installer.rating_avg.desc()),
                Installer.id,
            )
            .limit(remaining)
        )
        matched.extend(nearby)
    return matched
