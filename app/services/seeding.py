"""Reference data, content and the development-only demo accounts.

- Locations are upserted on every start-up (`seed-locations`).
- Content (blog articles, the client's directory of EV installers, showcase profiles) is
  applied in named batches (`seed-content`, also on every start-up). Each batch is inserted
  once and recorded in `seed_batches`, so later edits or deletions by the admin are kept.
- Demo login accounts (`seed-demo`) exist only outside production.
"""

import json
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import case, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import get_settings
from app.core.enums import (
    AccreditationScheme,
    BlogPostStatus,
    DirectoryColumn,
    InstallerSource,
    InstallerStatus,
    Plan,
    ReviewStatus,
    Role,
)
from app.models import (
    BlogPost,
    Installer,
    InstallerAccreditation,
    InstallerPhoto,
    Location,
    Review,
    SeedBatch,
    User,
)
from app.models.base import utcnow
from app.models.installer import DEFAULT_COVERAGE_RADIUS_MILES
from app.schemas.blog import BlogPostCreate
from app.services import blog, installers, reviews
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


# Photos shipped with the website (frontend/public/images/locations/). They belong to the
# seed file; any other photo (one the admin uploaded) belongs to the admin.
BUNDLED_LOCATION_PHOTOS = "/images/locations/"
_PHOTO_FIELDS = ("image_url", "image_alt", "image_credit")
# Written when a location is first created, then edited by the admin only.
_ADMIN_MANAGED_LOCATION_FIELDS = frozenset({"intro", *_PHOTO_FIELDS})


def _location_rows() -> list[dict[str, Any]]:
    """`data/locations.json`, checked: unique slugs, and one town per directory slot."""
    rows: list[dict[str, Any]] = []
    slots: set[tuple[DirectoryColumn, int]] = set()
    slugs: set[str] = set()
    for entry in _load("locations.json"):
        column = entry.get("directory_column")
        position = entry.get("directory_position")
        if column is not None:
            column = DirectoryColumn(column)
            if not isinstance(position, int) or position < 1 or (column, position) in slots:
                raise SeedingError(f"{entry['slug']}: invalid directory position {position!r}.")
            slots.add((column, position))
        elif position is not None:
            raise SeedingError(f"{entry['slug']}: a directory position needs a column.")
        if entry["slug"] in slugs:
            raise SeedingError(f"{entry['slug']} is listed twice in locations.json.")
        slugs.add(entry["slug"])
        rows.append(
            {
                "slug": entry["slug"],
                "name": entry["name"],
                "region": entry["region"],
                "latitude": entry["latitude"],
                "longitude": entry["longitude"],
                "directory_column": column,
                "directory_position": position,
                "intro": entry.get("intro"),
                **{field: entry.get(field) for field in _PHOTO_FIELDS},
            }
        )
    return rows


async def seed_locations(session: AsyncSession) -> int:
    """Idempotently upsert `data/locations.json`; returns how many locations it holds.

    Names, coordinates and the directory layout always follow the file. The intro is only
    written when a location is created. The photo follows the file while the location has
    no photo or one of the bundled photos, so a photo the admin uploaded is never replaced.
    """
    rows = _location_rows()
    statement = insert(Location).values(rows)
    updatable = [
        column
        for column in rows[0]
        if column != "slug" and column not in _ADMIN_MANAGED_LOCATION_FIELDS
    ]
    bundled_or_none = or_(
        Location.image_url.is_(None), Location.image_url.startswith(BUNDLED_LOCATION_PHOTOS)
    )
    photo = {
        field: case((bundled_or_none, statement.excluded[field]), else_=getattr(Location, field))
        for field in _PHOTO_FIELDS
    }
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[Location.slug],
            set_={column: statement.excluded[column] for column in updatable}
            | photo
            | {"updated_at": utcnow()},
        )
    )
    await session.commit()
    return len(rows)


def _sample_posts() -> list[tuple[BlogPostCreate, int]]:
    """`data/blog.json`, validated like an admin's request: (post, days since publishing)."""
    return [
        (
            BlogPostCreate.model_validate(
                {key: value for key, value in entry.items() if key != "days_ago"}
            ),
            entry["days_ago"],
        )
        for entry in _load("blog.json")["posts"]
    ]


async def _insert_blog_samples(session: AsyncSession) -> int:
    """Add the sample articles whose slug is free; no commit."""
    samples = _sample_posts()
    existing = set(
        await session.scalars(
            select(BlogPost.slug).where(BlogPost.slug.in_([post.slug for post, _ in samples]))
        )
    )
    now = utcnow()
    added = 0
    for post, days_ago in samples:
        if post.slug in existing:
            continue
        published_at = now - timedelta(days=days_ago)
        session.add(
            BlogPost(
                **post.model_dump(exclude={"status", "published_at"}),
                category_slug=installers.slugify(post.category, fallback="general"),
                reading_minutes=blog.reading_minutes(post.body),
                status=BlogPostStatus.PUBLISHED,
                published_at=published_at,
                created_at=published_at,
                updated_at=published_at,
            )
        )
        added += 1
    await session.flush()
    return added


async def seed_blog(session: AsyncSession, *, only_if_empty: bool = False) -> int:
    """Publish the sample posts that do not exist yet; returns how many were added.

    Safe to re-run: a post whose slug already exists (sample or admin-written) is left alone.
    With `only_if_empty`, nothing is added once the blog has any post at all.
    """
    if only_if_empty and await session.scalar(select(BlogPost.id).limit(1)) is not None:
        return 0
    added = await _insert_blog_samples(session)
    await session.commit()
    return added


async def purge_blog(session: AsyncSession) -> int:
    """Delete the sample posts (matched by slug); posts the admin created are kept."""
    slugs = [post.slug for post, _ in _sample_posts()]
    result = await session.execute(
        delete(BlogPost).where(BlogPost.slug.in_(slugs)).returning(BlogPost.id)
    )
    await session.commit()
    return len(result.all())


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


# ---- Content batches ---------------------------------------------------------------


async def _locations_by_slug(session: AsyncSession) -> dict[str, Location]:
    locations = {location.slug: location for location in await session.scalars(select(Location))}
    if not locations:
        raise SeedingError("Seed locations first: python -m app.cli seed-locations")
    return locations


async def _existing_business_names(session: AsyncSession) -> set[str]:
    return set(await session.scalars(select(func.lower(Installer.business_name))))


def _listing_description(name: str, locality: str | None, postcode: str, town: str) -> str:
    based = locality if locality and locality.lower() != town.lower() else town
    district = postcode.split(" ")[0]
    return (
        f"{name} is an electrical business based in {based} ({district}), listed on "
        f"PickASparky for EV charger installation in {town} and the surrounding area."
    )


async def insert_listings(session: AsyncSession) -> int:
    """The client's directory of EV installers (`data/listings.json`) as free basic listings.

    Each listing is approved and public on the Free plan, has no account (so it receives no
    leads), and can be claimed by the business through its email address. Businesses that are
    already listed under the same name are skipped. No commit.
    """
    locations = await _locations_by_slug(session)
    known = await _existing_business_names(session)
    now = utcnow()
    added = 0
    for entry in _load("listings.json")["listings"]:
        name = entry["business_name"]
        if name.lower() in known:
            continue
        location = locations[entry["location"]]
        address = ", ".join(part for part in (entry["street_address"], entry["locality"]) if part)
        session.add(
            Installer(
                slug=await installers.unique_slug(session, name),
                business_name=name,
                contact_name="",
                phone=entry["phone"] or "",
                tagline=f"EV charger installation in {location.name}",
                description=_listing_description(
                    name, entry["locality"], entry["postcode"], location.name
                ),
                base_postcode=entry["postcode"],
                # The listing serves its town: it is placed at the town's centre.
                latitude=location.latitude,
                longitude=location.longitude,
                town=location.name,
                location=location,
                coverage_radius_miles=DEFAULT_COVERAGE_RADIUS_MILES,
                services=["ev_charger_installation"],
                areas_covered=[location.name],
                status=InstallerStatus.APPROVED,
                plan=Plan.FREE,
                approved_at=now,
                source=InstallerSource.IMPORTED,
                contact_email=entry["email"],
                address=address[:255] or None,
            )
        )
        known.add(name.lower())
        added += 1
    await session.flush()
    return added


async def insert_showcase(session: AsyncSession) -> int:
    """The showcase profiles and reviews from the design (`data/demo.json`), unclaimed.

    Outside production these always load. In production they load only with
    SEED_SHOWCASE=true: the businesses and reviews are illustrative, and publishing
    invented reviews as genuine is not allowed on a live consumer site. No commit.
    """
    locations = await _locations_by_slug(session)
    known = await _existing_business_names(session)
    demo = _load("demo.json")
    now = utcnow()
    created: dict[str, Installer] = {}
    for entry in demo["installers"]:
        if entry["business_name"].lower() in known:
            continue
        location = locations[entry["location"]]
        status = InstallerStatus(entry["status"])
        installer = Installer(
            slug=await installers.unique_slug(session, entry["business_name"]),
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
            source=InstallerSource.IMPORTED,
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
        created[installer.business_name] = installer
    await session.flush()

    for entry in demo["reviews"]:
        installer = created.get(entry["installer"])
        if installer is None:
            continue
        written_at = now - timedelta(days=entry["days_ago"], hours=entry["days_ago"] % 7)
        session.add(
            Review(
                installer_id=installer.id,
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
    for installer in created.values():
        await reviews.recompute_rating(session, installer.id)
    return len(created)


def _showcase_allowed() -> bool:
    settings = get_settings()
    return not settings.is_production or settings.seed_showcase


ContentBatch = tuple[str, Callable[[AsyncSession], Awaitable[int]], Callable[[], bool]]

# Applied in this order, each once. Never rename a batch that has shipped: add a new one.
CONTENT_BATCHES: tuple[ContentBatch, ...] = (
    ("blog-articles-2026-10", _insert_blog_samples, lambda: True),
    ("directory-listings-2026-10", insert_listings, lambda: True),
    ("showcase-installers-2026-10", insert_showcase, _showcase_allowed),
)
_SEED_LOCK = 4_242_001  # pg_advisory_xact_lock key: one seeder at a time


async def seed_content(session: AsyncSession) -> list[tuple[str, int]]:
    """Apply every content batch not applied yet; returns `(batch, records added)` pairs."""
    applied: list[tuple[str, int]] = []
    for name, insert_batch, allowed in CONTENT_BATCHES:
        if not allowed():
            continue
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _SEED_LOCK})
        if await session.get(SeedBatch, name) is not None:
            await session.rollback()
            continue
        added = await insert_batch(session)
        session.add(SeedBatch(name=name))
        await session.commit()
        applied.append((name, added))
    return applied


# ---- Demo accounts (never production) ------------------------------------------------


async def purge_demo(session: AsyncSession) -> int:
    """Delete every demo account. Their listings stay, unclaimed again."""
    _require_non_production()
    demo_users = select(User.id).where(User.email.like(f"%@{DEMO_EMAIL_DOMAIN}"))
    await session.execute(
        update(Installer).where(Installer.user_id.in_(demo_users)).values(claimed_at=None)
    )
    result = await session.execute(
        delete(User).where(User.email.like(f"%@{DEMO_EMAIL_DOMAIN}")).returning(User.id)
    )
    await session.commit()
    return len(result.all())


async def seed_demo(session: AsyncSession) -> int:
    """Demo logins for development: the demo admin, and an account for every showcase
    profile (`<slug>@demo.pickasparky.test`). Loads the showcase profiles if missing.
    Returns how many showcase profiles have a demo account."""
    _require_non_production()
    await purge_demo(session)
    await insert_showcase(session)

    now = utcnow()
    session.add(
        User(
            email=DEMO_ADMIN_EMAIL,
            password_hash=await security.hash_password(DEMO_ADMIN_PASSWORD),
            role=Role.ADMIN,
            email_verified_at=now,
        )
    )
    names = [entry["business_name"] for entry in _load("demo.json")["installers"]]
    showcase = await session.scalars(
        select(Installer).where(Installer.business_name.in_(names), Installer.user_id.is_(None))
    )
    password_hash = await security.hash_password(DEMO_INSTALLER_PASSWORD)
    claimed = 0
    for installer in showcase:
        installer.user = User(
            email=f"{installer.slug}@{DEMO_EMAIL_DOMAIN}",
            password_hash=password_hash,
            role=Role.INSTALLER,
            email_verified_at=now,
        )
        installer.claimed_at = now
        claimed += 1
    await session.commit()
    return claimed
