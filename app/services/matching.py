"""Matching quote requests to installers by coverage, plan and distance."""

from sqlalchemy import func, nulls_last, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.enums import InstallerStatus
from app.core.plans import capabilities_for, lead_receiving_plan_keys, sort_rank_expression
from app.models import Installer
from app.services.geo import installer_covers_point, installer_distance_to


def notifiable() -> tuple:
    """SQL filters selecting the installers who are told about a new enquiry.

    Every approved installer with an account, Free and paid alike (pending, rejected,
    paused and deleted ones are excluded). Free installers get the notification but must
    upgrade before they can open the enquiry and respond. A listing nobody has claimed yet
    has no one to email, so it is left out.
    """
    return (
        Installer.status == InstallerStatus.APPROVED,
        Installer.user_id.is_not(None),
    )


async def count_in_range(session: AsyncSession, latitude: float, longitude: float) -> int:
    """How many installers able to quote (full lead access) cover a point.

    Free installers are notified of enquiries too, but cannot respond until they upgrade, so
    they are not counted when telling a homeowner who can quote in their area.
    """
    count = await session.scalar(
        select(func.count())
        .select_from(Installer)
        .where(
            *notifiable(),
            Installer.plan.in_(lead_receiving_plan_keys()),
            installer_covers_point(latitude, longitude),
        )
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
    limit: int | None = None,
    nearby: bool = True,
) -> list[Installer]:
    """Pick the installers to receive a quote request.

    A requested installer that accepts direct quotes always comes first. The rest are all
    the notifiable installers whose coverage circle contains the point, best plan first,
    then nearest, then highest rated: there is no cap, because only the first few to respond
    may quote (see `conversations`), not the first few to be told. `limit` is for callers
    that want fewer. `nearby=False` sends only to the requested installer.
    """
    matched: list[Installer] = []
    if (
        target is not None
        and target.user_id is not None
        and capabilities_for(target.plan).accepts_direct_quotes
    ):
        matched.append(target)

    remaining = None if limit is None else limit - len(matched)
    if nearby and (remaining is None or remaining > 0):
        statement = (
            select(Installer)
            .where(
                *notifiable(),
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
        )
        if remaining is not None:
            statement = statement.limit(remaining)
        matched.extend(await session.scalars(statement))
    return matched
