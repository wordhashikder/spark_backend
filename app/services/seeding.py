"""Reference and demo data: locations, the first admin, and the development-only demo set."""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import get_settings
from app.core.enums import AccreditationScheme, InstallerStatus, Plan, ReviewStatus, Role
from app.models import (
    Installer,
    InstallerAccreditation,
    InstallerPhoto,
    Location,
    Review,
    User,
)
from app.models.base import utcnow
from app.services import installers, reviews
from app.services.geocoding import GeocodedPostcode

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEMO_EMAIL_DOMAIN = "demo.pickasparky.test"
DEMO_ADMIN_EMAIL = f"admin@{DEMO_EMAIL_DOMAIN}"
DEMO_ADMIN_PASSWORD = "DemoAdmin123!"  # noqa: S105 - published demo credential, never production
DEMO_INSTALLER_PASSWORD = "DemoPass123!"  # noqa: S105 - published demo credential, never production


class SeedingError(Exception):
    """A seeding command cannot run as asked; the message is shown to the operator."""


def _load(name: str) -> Any:
    return json.loads((_DATA_DIR / name).read_text(encoding="utf-8"))


def _require_non_production() -> None:
    if get_settings().is_production:
        raise SeedingError("Demo data must never be loaded when ENVIRONMENT=production.")


async def seed_locations(session: AsyncSession) -> int:
    """Idempotently upsert `data/locations.json`; returns how many locations it holds."""
    rows = [
        {
            "slug": entry["slug"],
            "name": entry["name"],
            "region": entry["region"],
            "latitude": entry["latitude"],
            "longitude": entry["longitude"],
            "is_popular": entry.get("is_popular", False),
            "popular_rank": entry.get("popular_rank"),
            "intro": entry.get("intro"),
            "image_url": entry.get("image_url"),
        }
        for entry in _load("locations.json")
    ]
    statement = insert(Location).values(rows)
    updatable = [column for column in rows[0] if column != "slug"]
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[Location.slug],
            set_={column: statement.excluded[column] for column in updatable}
            | {"updated_at": utcnow()},
        )
    )
    await session.commit()
    return len(rows)


async def create_admin(session: AsyncSession, email: str, password: str) -> User:
    """Create a verified admin account; refuses to touch an existing account."""
    if await session.scalar(select(User.id).where(User.email == email)) is not None:
        raise SeedingError(f"An account with the email {email} already exists.")
    admin = User(
        email=email,
        password_hash=await security.hash_password(password),
        role=Role.ADMIN,
        email_verified_at=utcnow(),
    )
    session.add(admin)
    await session.commit()
    return admin


def demo_postcodes() -> list[GeocodedPostcode]:
    """Demo postcodes resolved to their town's coordinates, for offline development."""
    _require_non_production()
    by_slug = {entry["slug"]: entry for entry in _load("locations.json")}
    return [
        GeocodedPostcode(
            postcode=entry["postcode"],
            latitude=by_slug[entry["location"]]["latitude"],
            longitude=by_slug[entry["location"]]["longitude"],
            district=by_slug[entry["location"]]["name"],
            region=by_slug[entry["location"]]["region"],
        )
        for entry in _load("demo.json")["postcodes"]
    ]


async def purge_demo(session: AsyncSession) -> int:
    """Delete every demo account (and, by cascade, its installer, reviews and leads)."""
    _require_non_production()
    result = await session.execute(
        delete(User).where(User.email.like(f"%@{DEMO_EMAIL_DOMAIN}")).returning(User.id)
    )
    await session.commit()
    return len(result.all())


async def seed_demo(session: AsyncSession) -> int:
    """Replace the demo data set; returns the number of demo installers created."""
    _require_non_production()
    await purge_demo(session)
    locations = {location.slug: location for location in await session.scalars(select(Location))}
    if not locations:
        raise SeedingError("Seed locations first: python -m app.cli seed-locations")

    demo = _load("demo.json")
    now = utcnow()
    session.add(
        User(
            email=DEMO_ADMIN_EMAIL,
            password_hash=await security.hash_password(DEMO_ADMIN_PASSWORD),
            role=Role.ADMIN,
            email_verified_at=now,
        )
    )

    by_name: dict[str, Installer] = {}
    for entry in demo["installers"]:
        location = locations[entry["location"]]
        slug = installers.slugify(entry["business_name"])
        status = InstallerStatus(entry["status"])
        installer = Installer(
            user=User(
                email=f"{slug}@{DEMO_EMAIL_DOMAIN}",
                password_hash=await security.hash_password(DEMO_INSTALLER_PASSWORD),
                role=Role.INSTALLER,
                email_verified_at=now,
            ),
            slug=slug,
            business_name=entry["business_name"],
            contact_name=entry["contact_name"],
            phone=entry["phone"],
            tagline=entry["tagline"],
            description=entry["description"],
            base_postcode=entry["base_postcode"],
            latitude=location.latitude,
            longitude=location.longitude,
            town=location.name,
            location=location,
            coverage_radius_miles=entry["coverage_radius_miles"],
            years_experience=entry["years_experience"],
            logo_url=entry.get("logo_url"),
            services=entry["services"],
            areas_covered=entry["areas_covered"],
            status=status,
            plan=Plan(entry["plan"]),
            requested_plan=Plan(entry["plan"]),
            is_featured=entry["is_featured"],
            approved_at=now if status is InstallerStatus.APPROVED else None,
            accreditations=[
                InstallerAccreditation(scheme=AccreditationScheme(scheme), verified=True)
                for scheme in entry["accreditations"]
            ],
            photos=[
                InstallerPhoto(
                    url=url, alt=f"{entry['business_name']} installation", position=index
                )
                for index, url in enumerate(entry.get("photos", []))
            ],
        )
        session.add(installer)
        by_name[installer.business_name] = installer
    await session.flush()

    for entry in demo["reviews"]:
        written_at = now - timedelta(days=entry["days_ago"], hours=entry["days_ago"] % 7)
        session.add(
            Review(
                installer_id=by_name[entry["installer"]].id,
                rating=entry["rating"],
                title=entry["title"],
                body=entry["body"],
                author_name=entry["author_name"],
                author_location=entry["author_location"],
                status=ReviewStatus.PUBLISHED,
                published_at=written_at,
                created_at=written_at,
                updated_at=written_at,
            )
        )
    await session.flush()
    for installer in by_name.values():
        await reviews.recompute_rating(session, installer.id)
    await session.commit()
    return len(by_name)
