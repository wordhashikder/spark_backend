"""
Installer search for the public /search/ page.

Filters are combined with AND. Results are grouped by plan, best plan first (Premium, then
Pro, then Free), and installers inside a group rotate every hour so each gets a turn at the
top. The order is the same for the whole hour, so paging through it is stable. The town
pages keep their own ordering (`installers._listing_order`).
"""

import re
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.enums import InstallerStatus, Service
from app.core.exceptions import NotFoundError
from app.core.plans import sort_rank_expression
from app.models import AccreditationScheme, Installer, InstallerAccreditation, Location
from app.services import locations
from app.services.geo import installer_distance_to
from app.services.geocoding import Geocoder, normalise_postcode

ROTATION_SECONDS = 60 * 60
DEFAULT_DISTANCE_MILES = 25
MAX_DISTANCE_MILES = 200
# "WA10", "M1": the first half of a postcode.
_OUTWARD_CODE = re.compile(r"[A-Z]{1,2}\d[A-Z\d]?")


@dataclass(frozen=True, slots=True)
class SearchQuery:
    # General search: a postcode, a town, a company name, a service or an accreditation.
    text: str | None = None
    # Only the company's name.
    company: str | None = None
    # A town: its address (slug) or its name.
    location: str | None = None
    service: Service | None = None
    accreditation: str | None = None
    # Miles around a postcode searched in `text`.
    distance_miles: int = DEFAULT_DISTANCE_MILES


def rotation_bucket(now: float | None = None) -> int:
    """The current hour; the order of installers within a plan changes when it does."""
    return int((time.time() if now is None else now) // ROTATION_SECONDS)


def search_order(bucket: int) -> tuple[ColumnElement[Any], ...]:
    """Best plan first; within a plan a shuffle that is fixed for the hour."""
    shuffle = func.md5(func.concat(cast(Installer.id, String), f":{bucket}"))
    return (sort_rank_expression(Installer.plan).desc(), Installer.plan, shuffle, Installer.id)


def _contains(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _service_keys_matching(text: str) -> list[str]:
    needle = text.lower()
    return [
        service.value
        for service in Service
        if needle in service.label.lower() or needle in service.value.replace("_", " ")
    ]


async def _text_filter(text: str, query: SearchQuery, geocoder: Geocoder) -> ColumnElement[bool]:
    postcode = normalise_postcode(text)
    if postcode is not None:
        place = await geocoder.lookup(postcode)
        return installer_distance_to(place.latitude, place.longitude) <= query.distance_miles

    pattern = _contains(text)
    matches: list[ColumnElement[bool]] = [
        Installer.business_name.ilike(pattern, escape="\\"),
        Installer.town.ilike(pattern, escape="\\"),
        Installer.location.has(Location.name.ilike(pattern, escape="\\")),
    ]
    if _OUTWARD_CODE.fullmatch(text.upper()):
        matches.append(Installer.base_postcode.ilike(f"{text.upper()} %"))
    if services := _service_keys_matching(text):
        matches.append(Installer.services.overlap(services))
    schemes = select(AccreditationScheme.key).where(
        or_(
            AccreditationScheme.name.ilike(pattern, escape="\\"),
            AccreditationScheme.key.ilike(pattern, escape="\\"),
        )
    )
    matches.append(
        Installer.id.in_(
            select(InstallerAccreditation.installer_id).where(
                InstallerAccreditation.scheme.in_(schemes)
            )
        )
    )
    return or_(*matches)


async def _location_filter(session: AsyncSession, value: str) -> ColumnElement[bool]:
    """The town pages' own rule when the town exists; otherwise a match on the town's name."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    try:
        location = await locations.get_by_slug(session, slug)
    except NotFoundError:  # not a known town: fall back to a match on its name
        pattern = _contains(value)
        return or_(
            Installer.town.ilike(pattern, escape="\\"),
            Installer.location.has(Location.name.ilike(pattern, escape="\\")),
        )
    return locations.installer_serves_location(location)


async def search(
    session: AsyncSession,
    query: SearchQuery,
    geocoder: Geocoder,
    *,
    offset: int,
    limit: int,
    now: float | None = None,
) -> tuple[list[Installer], int]:
    """Approved installers matching every filter given, best plan first, rotating hourly."""
    filters: list[ColumnElement[bool]] = [Installer.status == InstallerStatus.APPROVED]
    if query.text:
        filters.append(await _text_filter(query.text, query, geocoder))
    if query.company:
        filters.append(Installer.business_name.ilike(_contains(query.company), escape="\\"))
    if query.location:
        filters.append(await _location_filter(session, query.location))
    if query.service is not None:
        filters.append(Installer.services.contains([query.service.value]))
    if query.accreditation:
        filters.append(
            Installer.id.in_(
                select(InstallerAccreditation.installer_id).where(
                    InstallerAccreditation.scheme == query.accreditation
                )
            )
        )

    total = await session.scalar(select(func.count()).select_from(Installer).where(*filters))
    found = await session.scalars(
        select(Installer)
        .where(*filters)
        .options(joinedload(Installer.location))
        .order_by(*search_order(rotation_bucket(now)))
        .offset(offset)
        .limit(limit)
    )
    return list(found), total or 0