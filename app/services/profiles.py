"""Public profile content for listings PickASparky added from a directory.

A listing from the client's directory only has a name, a phone number, an email and an
address. This builds the rest of a useful profile page from facts that are true of every
listing (where it is, which towns are nearby, how enquiries work). It never invents
anything about the business itself: no years of experience, accreditations, prices,
reviews or claims of quality. Businesses add the rest themselves when they claim the page.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Installer, Location
from app.services.geo import haversine_miles

NEARBY_LIMIT = 4
# The wording of the first generation (see `seeding._listing_description`); a description
# that still reads like this has not been touched by a person and may be regenerated.
_OLD_STUB_MARKER = "is an electrical business based in"


@dataclass(frozen=True, slots=True)
class Profile:
    tagline: str
    description: str
    areas_covered: list[str]


def _pick(seed: str, options: Sequence[str]) -> str:
    """A stable choice per business, so pages differ but never change between runs."""
    digest = hashlib.sha256(seed.encode()).digest()
    return options[digest[0] % len(options)]


def _list_phrase(items: Sequence[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def nearby_names(
    locations: Sequence[Location], *, latitude: float, longitude: float, home: str, radius: int
) -> list[str]:
    """The nearest town pages within the coverage radius, excluding the home town."""
    found = sorted(
        (
            (haversine_miles(latitude, longitude, place.latitude, place.longitude), place.name)
            for place in locations
            if place.name != home
        ),
    )
    return [name for miles, name in found if miles <= radius][:NEARBY_LIMIT]


def build(
    *,
    business_name: str,
    town: str,
    locality: str | None,
    postcode: str,
    nearby: Sequence[str],
    radius: int,
) -> Profile:
    district = postcode.split(" ")[0].upper()
    base = locality if locality and locality.lower() != town.lower() else None
    where = f"{base}, {town}" if base else town
    seed = business_name.lower()
    opening = _pick(
        seed,
        (
            f"{business_name} is an electrical business based in {where} ({district}) and listed "
            f"on PickASparky for EV charger installation.",
            f"Based in {where} ({district}), {business_name} is listed on PickASparky as an "
            f"installer of electric vehicle chargers.",
            f"{business_name} is listed on PickASparky for EV charger installation, working "
            f"from {where} ({district}).",
        ),
    )
    reach = (
        f"{business_name} covers {town} and the surrounding area, including "
        f"{_list_phrase(list(nearby))}."
        if nearby
        else f"{business_name} covers {town} and the surrounding area, within about {radius} miles."
    )
    enquiries = _pick(
        seed[::-1],
        (
            "Use the request form on this page to ask about a home or workplace charger. "
            "There is no obligation, and you can compare other nearby installers before you "
            "decide.",
            "To ask about a charger for your home or business, send a request using the form "
            "on this page. It is free, and you are under no obligation to go ahead.",
            "Send a request with the form on this page to find out what installing a charger "
            "would involve. It costs nothing and you can compare other local installers too.",
        ),
    )
    safety = (
        "Before any work starts, ask for proof of registration, insurance and a certificate "
        "for the finished installation."
    )
    return Profile(
        tagline=f"EV charger installation in {town}"[:120],
        description=f"{opening} {reach}\n\n{enquiries} {safety}",
        areas_covered=[town, *nearby][:20],
    )


async def fill_listing(session: AsyncSession, installer: Installer) -> None:
    """Give a new, unclaimed listing the standard profile wherever the team left it blank."""
    if installer.description and installer.areas_covered:
        return
    places = await published_locations(session)
    profile = build(
        business_name=installer.business_name,
        town=installer.town,
        locality=None,
        postcode=installer.base_postcode,
        nearby=nearby_names(
            places,
            latitude=installer.latitude,
            longitude=installer.longitude,
            home=installer.town,
            radius=installer.coverage_radius_miles,
        ),
        radius=installer.coverage_radius_miles,
    )
    installer.tagline = installer.tagline or profile.tagline
    installer.description = installer.description or profile.description
    installer.areas_covered = installer.areas_covered or profile.areas_covered


def is_generated_stub(description: str | None) -> bool:
    """A description from the first, one-line generation (never edited by a person)."""
    return bool(description) and _OLD_STUB_MARKER in (description or "") and len(description) < 260


async def published_locations(session: AsyncSession) -> list[Location]:
    return list(await session.scalars(select(Location).where(Location.is_published)))
