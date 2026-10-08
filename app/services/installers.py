"""Installer profiles: public listing queries, the installer's own profile and its media."""

import re
import unicodedata
import uuid

from sqlalchemy import func, nulls_last, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.enums import InstallerStatus, Plan
from app.core.exceptions import FieldValidationError, ForbiddenError, NotFoundError
from app.core.plans import capabilities_for, sort_rank_expression
from app.models import Installer, InstallerAccreditation, InstallerPhoto, User
from app.schemas.installer import AccreditationInput, InstallerUpdate
from app.services import locations
from app.services.geo import installer_distance_to
from app.services.geocoding import GeocodedPostcode, Geocoder, PostcodeNotFoundError
from app.services.storage import ImageStorage, discard_quietly, validate_image

MAX_SIMILAR = 8
_SLUG_MAX_LENGTH = 120
# Path segments under `/installers/` that must never be shadowed by a business slug.
_RESERVED_SLUGS = frozenset({"me"})
_WITH_PROFILE = (
    joinedload(Installer.location),
    selectinload(Installer.accreditations),
    selectinload(Installer.photos),
)
_LISTING_ORDER = (
    sort_rank_expression(Installer.plan).desc(),
    Installer.is_featured.desc(),
    nulls_last(Installer.rating_avg.desc()),
    Installer.review_count.desc(),
    Installer.business_name,
    Installer.id,
)


class PlanLimitError(ForbiddenError):
    code = "plan_limit_reached"
    message = "Your plan does not allow any more gallery photos."


def slugify(value: str, fallback: str = "installer") -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    return slug[:_SLUG_MAX_LENGTH].strip("-") or fallback


async def unique_slug(session: AsyncSession, business_name: str) -> str:
    """Slug for a business name, de-duplicated with a numeric suffix (`name`, `name-2`, ...)."""
    base = slugify(business_name)
    taken = set(
        await session.scalars(
            select(Installer.slug).where(
                or_(Installer.slug == base, Installer.slug.like(f"{base}-%"))
            )
        )
    )
    taken |= _RESERVED_SLUGS
    if base not in taken:
        return base
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


async def geocode_or_field_error(geocoder: Geocoder, postcode: str, field: str) -> GeocodedPostcode:
    """Geocode a postcode, reporting an unknown one as a validation error on `field`."""
    try:
        return await geocoder.lookup(postcode)
    except PostcodeNotFoundError as exc:
        raise FieldValidationError({field: "We could not find that postcode."}) from exc


async def create(
    session: AsyncSession,
    *,
    user: User,
    business_name: str,
    contact_name: str,
    phone: str,
    requested_plan: Plan,
    place: GeocodedPostcode,
) -> Installer:
    """Add a pending, free-plan installer based at `place` (the caller commits)."""
    location = await locations.nearest(session, place.latitude, place.longitude)
    installer = Installer(
        user=user,
        slug=await unique_slug(session, business_name),
        business_name=business_name,
        contact_name=contact_name,
        phone=phone,
        requested_plan=requested_plan,
        base_postcode=place.postcode,
        latitude=place.latitude,
        longitude=place.longitude,
        town=place.district or location.name,
        location=location,
    )
    session.add(installer)
    return installer


async def list_public(
    session: AsyncSession,
    *,
    location_slug: str | None,
    featured: bool | None,
    offset: int,
    limit: int,
) -> tuple[list[Installer], int]:
    """Approved installers, optionally only those serving a location, in listing order."""
    filters = [Installer.status == InstallerStatus.APPROVED]
    if location_slug is not None:
        location = await locations.get_by_slug(session, location_slug)
        filters.append(locations.installer_serves_location(location))
    if featured is not None:
        filters.append(Installer.is_featured.is_(featured))

    total = await session.scalar(select(func.count()).select_from(Installer).where(*filters))
    installers = await session.scalars(
        select(Installer)
        .where(*filters)
        .options(joinedload(Installer.location))
        .order_by(*_LISTING_ORDER)
        .offset(offset)
        .limit(limit)
    )
    return list(installers), total or 0


async def get_public(session: AsyncSession, slug: str) -> Installer:
    installer = await session.scalar(
        select(Installer)
        .where(Installer.slug == slug, Installer.status == InstallerStatus.APPROVED)
        .options(*_WITH_PROFILE)
    )
    if installer is None:
        raise NotFoundError("Installer not found.")
    return installer


async def list_similar(session: AsyncSession, slug: str, limit: int) -> list[Installer]:
    """Other approved installers, nearest to this one first."""
    installer = await get_public(session, slug)
    similar = await session.scalars(
        select(Installer)
        .where(Installer.status == InstallerStatus.APPROVED, Installer.id != installer.id)
        .options(joinedload(Installer.location))
        .order_by(installer_distance_to(installer.latitude, installer.longitude), Installer.id)
        .limit(min(limit, MAX_SIMILAR))
    )
    return list(similar)


async def get_for_user(session: AsyncSession, user_id: uuid.UUID) -> Installer | None:
    return await session.scalar(
        select(Installer).where(Installer.user_id == user_id).options(*_WITH_PROFILE)
    )


async def update_profile(
    session: AsyncSession, installer: Installer, data: InstallerUpdate, geocoder: Geocoder
) -> Installer:
    """Apply the fields present in `data`; a new postcode moves the installer's base."""
    changes = data.model_dump(exclude_unset=True, exclude={"accreditations", "base_postcode"})
    if "services" in changes:
        changes["services"] = [service.value for service in data.services or []]
    for name, value in changes.items():
        setattr(installer, name, value)

    if data.base_postcode is not None and data.base_postcode != installer.base_postcode:
        place = await geocode_or_field_error(geocoder, data.base_postcode, "base_postcode")
        location = await locations.nearest(session, place.latitude, place.longitude)
        installer.base_postcode = place.postcode
        installer.latitude = place.latitude
        installer.longitude = place.longitude
        installer.town = place.district or location.name
        installer.location = location

    if data.accreditations is not None:
        _replace_accreditations(installer, data.accreditations)

    await session.commit()
    return installer


def _replace_accreditations(installer: Installer, wanted: list[AccreditationInput]) -> None:
    """Make the installer's accreditations match `wanted`.

    Verification is granted by admins only: it survives an unchanged entry and is cleared
    whenever the registration number changes.
    """
    current = {accreditation.scheme: accreditation for accreditation in installer.accreditations}
    replacement = []
    for item in wanted:
        accreditation = current.get(item.scheme)
        if accreditation is None:
            accreditation = InstallerAccreditation(scheme=item.scheme, verified=False)
        if accreditation.registration_number != item.registration_number:
            accreditation.registration_number = item.registration_number
            accreditation.verified = False
        replacement.append(accreditation)
    installer.accreditations = replacement


async def set_logo(
    session: AsyncSession, installer: Installer, data: bytes, storage: ImageStorage
) -> Installer:
    validate_image(data)
    stored = await storage.upload(data, folder="logos")
    previous_public_id = installer.logo_public_id
    installer.logo_url = stored.url
    installer.logo_public_id = stored.public_id
    await session.commit()
    if previous_public_id:
        await discard_quietly(storage, previous_public_id)
    return installer


async def add_photo(
    session: AsyncSession,
    installer: Installer,
    data: bytes,
    alt: str | None,
    storage: ImageStorage,
) -> InstallerPhoto:
    if len(installer.photos) >= capabilities_for(installer.plan).max_gallery_photos:
        raise PlanLimitError
    validate_image(data)
    stored = await storage.upload(data, folder="gallery")
    photo = InstallerPhoto(
        url=stored.url,
        public_id=stored.public_id,
        alt=alt,
        position=max((existing.position for existing in installer.photos), default=-1) + 1,
    )
    installer.photos.append(photo)
    await session.commit()
    return photo


async def delete_photo(
    session: AsyncSession, installer: Installer, photo_id: uuid.UUID, storage: ImageStorage
) -> None:
    photo = next((photo for photo in installer.photos if photo.id == photo_id), None)
    if photo is None:
        raise NotFoundError("Photo not found.")
    installer.photos.remove(photo)
    await session.commit()
    if photo.public_id:
        await discard_quietly(storage, photo.public_id)
