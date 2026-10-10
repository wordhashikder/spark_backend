"""Location queries (listing with installer counts, the directory, nearest-location lookup)
and the admin's management of each location's intro and photo."""

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DirectoryColumn, InstallerStatus
from app.core.exceptions import NotFoundError
from app.models import Installer, Location
from app.schemas.location import (
    AdminLocationUpdate,
    LocationDetail,
    LocationDirectory,
    LocationRef,
    LocationSummary,
)
from app.services.geo import distance_miles, installer_covers_point
from app.services.storage import ImageStorage, discard_quietly, validate_image


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
            slug=location.slug,
            name=location.name,
            region=location.region,
            latitude=location.latitude,
            longitude=location.longitude,
            installer_count=count,
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
        image_alt=location.image_alt,
        image_credit=location.image_credit,
        seo_title=location.seo_title,
        seo_description=location.seo_description,
    )


async def get_directory(session: AsyncSession) -> LocationDirectory:
    """The "Find trusted installers in your area" directory: the same four columns on every
    page, each in its set order. A location has at most one slot, so none is listed twice."""
    listed = await session.scalars(
        select(Location)
        .where(Location.directory_column.is_not(None))
        .order_by(Location.directory_position, Location.name)
    )
    columns: dict[DirectoryColumn, list[LocationRef]] = {column: [] for column in DirectoryColumn}
    for location in listed:
        columns[location.directory_column].append(LocationRef.model_validate(location))
    return LocationDirectory(
        nearby=columns[DirectoryColumn.NEARBY],
        popular=columns[DirectoryColumn.POPULAR],
        more_in_area=columns[DirectoryColumn.MORE_IN_AREA],
        other=columns[DirectoryColumn.OTHER],
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


# ---- Admin: intro and photo ---------------------------------------------------------


async def list_all(session: AsyncSession) -> list[Location]:
    return list(await session.scalars(select(Location).order_by(Location.name)))


async def list_all_with_counts(session: AsyncSession) -> list[tuple[Location, int]]:
    """Every location with its public installer count (back office)."""
    rows = await session.execute(
        select(Location, _installer_count().label("installer_count")).order_by(Location.name)
    )
    return [(location, count) for location, count in rows]


async def _get_for_update(session: AsyncSession, slug: str) -> Location:
    location = await session.scalar(select(Location).where(Location.slug == slug).with_for_update())
    if location is None:
        raise NotFoundError("Location not found.")
    return location


async def update_content(
    session: AsyncSession, slug: str, data: AdminLocationUpdate, storage: ImageStorage
) -> Location:
    """Change the fields that were sent. A new or cleared `image_url` releases an uploaded photo."""
    location = await _get_for_update(session, slug)
    changes = data.model_dump(include=data.model_fields_set)
    replaced_public_id = None
    if "image_url" in changes and changes["image_url"] != location.image_url:
        replaced_public_id = location.image_public_id
        location.image_public_id = None
    for field, value in changes.items():
        setattr(location, field, value)
    await session.commit()
    await discard_quietly(storage, replaced_public_id)
    return location


async def set_image(
    session: AsyncSession,
    slug: str,
    data: bytes,
    storage: ImageStorage,
    *,
    alt: str | None,
    credit: str | None,
) -> Location:
    """Upload a photo for the location page and replace the current one."""
    location = await _get_for_update(session, slug)
    validate_image(data)
    stored = await storage.upload(data, folder="locations")
    previous_public_id = location.image_public_id
    location.image_url = stored.url
    location.image_public_id = stored.public_id
    location.image_alt = alt or f"{location.name}, {location.region}"
    location.image_credit = credit
    await session.commit()
    await discard_quietly(storage, previous_public_id)
    return location


async def remove_image(session: AsyncSession, slug: str, storage: ImageStorage) -> Location:
    """Remove the photo: the page falls back to its generated local map."""
    location = await _get_for_update(session, slug)
    previous_public_id = location.image_public_id
    location.image_url = None
    location.image_alt = None
    location.image_credit = None
    location.image_public_id = None
    await session.commit()
    await discard_quietly(storage, previous_public_id)
    return location
