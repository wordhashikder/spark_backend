"""Location queries: listing with installer counts, the directory and nearest-location lookup."""

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import InstallerStatus
from app.core.exceptions import NotFoundError
from app.models import Installer, Location
from app.schemas.location import LocationDetail, LocationDirectory, LocationRef, LocationSummary
from app.services.geo import distance_miles, haversine_miles, installer_covers_point

DIRECTORY_GROUP_SIZE = 8
DEFAULT_DIRECTORY_ANCHOR = "manchester"


def installer_serves_location(location: Location) -> ColumnElement[bool]:
    """SQL predicate: the installer is based in `location` or its coverage circle contains it."""
    return or_(
        Installer.location_id == location.id,
        installer_covers_point(location.latitude, location.longitude),
    )


def _installer_count() -> ColumnElement[int]:
    """Correlated count of approved installers serving each row of `locations`."""
    serves = or_(
        Installer.location_id == Location.id,
        distance_miles(
            Installer.latitude, Installer.longitude, Location.latitude, Location.longitude
        )
        <= Installer.coverage_radius_miles,
    )
    return (
        select(func.count())
        .select_from(Installer)
        .where(Installer.status == InstallerStatus.APPROVED, serves)
        .correlate(Location)
        .scalar_subquery()
    )


async def get_by_slug(session: AsyncSession, slug: str) -> Location:
    location = await session.scalar(select(Location).where(Location.slug == slug))
    if location is None:
        raise NotFoundError("Location not found.")
    return location


async def list_with_counts(session: AsyncSession) -> list[LocationSummary]:
    rows = await session.execute(
        select(Location, _installer_count().label("installer_count")).order_by(Location.name)
    )
    return [
        LocationSummary(
            slug=location.slug, name=location.name, region=location.region, installer_count=count
        )
        for location, count in rows
    ]


async def get_detail(session: AsyncSession, slug: str) -> LocationDetail:
    row = (
        await session.execute(
            select(Location, _installer_count().label("installer_count")).where(
                Location.slug == slug
            )
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("Location not found.")
    location, count = row
    return LocationDetail(
        slug=location.slug,
        name=location.name,
        region=location.region,
        installer_count=count,
        latitude=location.latitude,
        longitude=location.longitude,
        intro=location.intro,
        image_url=location.image_url,
    )


async def get_directory(session: AsyncSession, near: str) -> LocationDirectory:
    """Group every location around the anchor: nearby, popular, more in the area, other."""
    locations = list(await session.scalars(select(Location).order_by(Location.name)))
    anchor = next((location for location in locations if location.slug == near), None)
    if anchor is None:
        raise NotFoundError("Location not found.")

    by_distance = sorted(
        (location for location in locations if location.id != anchor.id),
        key=lambda location: haversine_miles(
            anchor.latitude, anchor.longitude, location.latitude, location.longitude
        ),
    )
    nearby = by_distance[:DIRECTORY_GROUP_SIZE]
    more_in_area = by_distance[DIRECTORY_GROUP_SIZE : 2 * DIRECTORY_GROUP_SIZE]
    popular = sorted(
        (location for location in locations if location.is_popular),
        key=lambda location: (location.popular_rank is None, location.popular_rank, location.name),
    )[:DIRECTORY_GROUP_SIZE]

    listed = {location.id for location in (anchor, *nearby, *more_in_area, *popular)}
    other = [location for location in locations if location.id not in listed]

    def refs(group: list[Location]) -> list[LocationRef]:
        return [LocationRef.model_validate(location) for location in group]

    return LocationDirectory(
        anchor=LocationRef.model_validate(anchor),
        nearby=refs(nearby),
        popular=refs(popular),
        more_in_area=refs(more_in_area),
        other=refs(other[:DIRECTORY_GROUP_SIZE]),
    )


async def nearest(session: AsyncSession, latitude: float, longitude: float) -> Location:
    """The location closest to a point (every installer is attached to one)."""
    location = await session.scalar(
        select(Location)
        .order_by(distance_miles(Location.latitude, Location.longitude, latitude, longitude))
        .limit(1)
    )
    if location is None:
        raise RuntimeError("No locations are seeded; run `python -m app.cli seed-locations`.")
    return location
