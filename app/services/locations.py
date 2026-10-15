"""Location queries (listing with installer counts, the directory, nearest-location lookup)
and the admin's management of location pages: adding them, drafts, content and photo.

Draft locations (`is_published = false`) are invisible to the public site: lists, the
directory, the page itself and the sitemap (built from the list). Installers are never
attached to a draft, so publishing or unpublishing a page never moves anyone.
"""

import re

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import DirectoryColumn, InstallerStatus
from app.core.exceptions import ConflictError, FieldValidationError, NotFoundError
from app.models import Installer, Location
from app.schemas.location import (
    AdminLocationCreate,
    AdminLocationUpdate,
    LocationDetail,
    LocationDirectory,
    LocationRef,
    LocationSummary,
)
from app.services import installers as installer_service
from app.services.geo import distance_miles, installer_covers_point
from app.services.geocoding import Geocoder
from app.services.storage import ImageStorage, discard_quietly, validate_image

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PUBLISHED = Location.is_published.is_(True)


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
    """A published location (the public site's view)."""
    location = await session.scalar(select(Location).where(Location.slug == slug, _PUBLISHED))
    if location is None:
        raise NotFoundError("Location not found.")
    return location


async def list_with_counts(session: AsyncSession) -> list[LocationSummary]:
    rows = await session.execute(
        select(Location, _installer_count().label("installer_count"))
        .where(_PUBLISHED)
        .order_by(Location.name)
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
                Location.slug == slug, _PUBLISHED
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
        h1_heading=location.h1_heading,
        extra_title=location.extra_title,
        extra_body=location.extra_body,
        updated_at=location.updated_at,
    )


async def get_directory(session: AsyncSession) -> LocationDirectory:
    """The "Find trusted installers in your area" directory: the same four columns on every
    page, each in its set order. A location has at most one slot, so none is listed twice."""
    listed = await session.scalars(
        select(Location)
        .where(Location.directory_column.is_not(None), _PUBLISHED)
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
    """The published location closest to a point (every installer is attached to one)."""
    location = await session.scalar(
        select(Location)
        .where(_PUBLISHED)
        .order_by(distance_miles(Location.latitude, Location.longitude, latitude, longitude))
        .limit(1)
    )
    if location is None:
        raise RuntimeError("No locations are seeded; run `python -m app.cli seed-locations`.")
    return location


# ---- Admin: pages, drafts, content and photo -----------------------------------------


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


async def create(session: AsyncSession, data: AdminLocationCreate, geocoder: Geocoder) -> Location:
    """Add a town page, centred on a postcode. It starts as a draft unless published now."""
    place = await installer_service.geocode_or_field_error(geocoder, data.postcode, "postcode")
    slug = data.slug or installer_service.slugify(data.name, fallback="location")
    await _check_slug(session, slug)
    if await session.scalar(
        select(Location.id).where(func.lower(Location.name) == data.name.lower())
    ):
        raise FieldValidationError({"name": "A page for this town already exists."})
    location = Location(
        slug=slug,
        name=data.name,
        region=data.region or place.region or "United Kingdom",
        latitude=place.latitude,
        longitude=place.longitude,
        is_published=data.is_published,
    )
    session.add(location)
    await session.commit()
    return location


async def update_content(
    session: AsyncSession, slug: str, data: AdminLocationUpdate, storage: ImageStorage
) -> Location:
    """Change the fields that were sent. A new or cleared `image_url` releases an uploaded photo.

    The address (slug) can change only while the page is a draft, so published links and
    search results never break.
    """
    location = await _get_for_update(session, slug)
    changes = data.model_dump(include=data.model_fields_set)
    if "slug" in changes and changes["slug"] != location.slug:
        if location.is_published:
            raise FieldValidationError({"slug": "Unpublish the page before changing its address."})
        await _check_slug(session, changes["slug"])
    elif "slug" in changes:
        changes.pop("slug")
    replaced_public_id = None
    if "image_url" in changes and changes["image_url"] != location.image_url:
        replaced_public_id = location.image_public_id
        location.image_public_id = None
    for field, value in changes.items():
        setattr(location, field, value)
    await session.commit()
    await discard_quietly(storage, replaced_public_id)
    return location


async def _check_slug(session: AsyncSession, slug: str) -> None:
    if not _SLUG.fullmatch(slug) or len(slug) > 80:
        raise FieldValidationError(
            {"slug": "Use lowercase letters, numbers and single hyphens (e.g. st-albans)."}
        )
    if await session.scalar(select(Location.id).where(Location.slug == slug)):
        raise FieldValidationError({"slug": "Another page already uses this address."})


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


async def delete(session: AsyncSession, slug: str, storage: ImageStorage) -> None:
    """Remove a town page. Only an unpublished page with no installers can be deleted.

    Installers are placed at their nearest town, so removing a page that has some would
    leave them without one; the live page is unpublished first so its address never breaks.
    """
    location = await _get_for_update(session, slug)
    if location.is_published:
        raise ConflictError("Unpublish the page before deleting it.")
    attached = await session.scalar(
        select(func.count()).select_from(Installer).where(Installer.location_id == location.id)
    )
    if attached:
        raise ConflictError(
            f"{attached} installer(s) are placed in {location.name}. "
            "Move or delete them first, or keep the page as a draft."
        )
    public_id = location.image_public_id
    await session.delete(location)
    await session.commit()
    await discard_quietly(storage, public_id)
