"""What a live database holds after start-up: locations, the 193 listings and one admin."""

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.core import security
from app.core.config import Settings, get_settings
from app.core.enums import InstallerSource, InstallerStatus, Role, StaffRole
from app.models import BlogPost, Installer, Review, SeedBatch, User
from app.services import seeding

LISTINGS = "directory-listings-2026-10"
PASSWORD = "Str0ng-admin-pass-2026"


@pytest.fixture
def production(monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = get_settings().model_copy(update={"environment": "production"})
    monkeypatch.setattr(seeding, "get_settings", lambda: settings)
    return settings


def _with_admin(monkeypatch: pytest.MonkeyPatch, email: str | None, password: str | None) -> None:
    settings = get_settings().model_copy(update={"admin_email": email, "admin_password": password})
    monkeypatch.setattr(cli, "get_settings", lambda: settings)


async def _count(db: AsyncSession, model: type) -> int:
    return await db.scalar(select(func.count()).select_from(model)) or 0


async def test_production_holds_only_the_193_unclaimed_approved_listings(
    db: AsyncSession, production: Settings
):
    applied = await seeding.seed_content(db)

    assert [name for name, _ in applied] == [
        LISTINGS,
        "directory-profiles-2026-10b",
        "site-pages-2026-11",
    ]
    assert dict(applied)[LISTINGS] == 193
    assert await _count(db, Installer) == 193
    assert await _count(db, BlogPost) == 0
    assert await _count(db, Review) == 0
    assert await _count(db, User) == 0
    rows = list(await db.scalars(select(Installer)))
    assert {(r.status, r.source, r.user_id, r.claimed_at) for r in rows} == {
        (InstallerStatus.APPROVED, InstallerSource.IMPORTED, None, None)
    }
    assert all(r.location_id is not None and r.approved_at is not None for r in rows)

    # Start-up runs it every time: nothing is added twice or brought back.
    assert await seeding.seed_content(db) == []
    assert await _count(db, Installer) == 193
    assert await _count(db, SeedBatch) == 3


async def test_development_also_gets_sample_articles_and_showcase_but_no_logins(
    db: AsyncSession,
):
    await seeding.seed_content(db)

    assert await _count(db, BlogPost) == 6
    assert await _count(db, Installer) > 193
    assert await _count(db, Review) > 0
    assert await _count(db, User) == 0  # no demo accounts, in any environment


async def test_sample_blog_posts_cannot_be_loaded_in_production(
    db: AsyncSession, production: Settings
):
    with pytest.raises(seeding.SeedingError, match="never be loaded"):
        await seeding.seed_blog(db)
    assert await _count(db, BlogPost) == 0


def test_the_193_listings_are_complete_and_unique():
    listings = seeding._load("listings.json")["listings"]
    locations = {entry["slug"] for entry in seeding._load("locations.json")}

    assert len(listings) == 193
    assert len({entry["business_name"].lower() for entry in listings}) == 193
    assert len({entry["email"] for entry in listings if entry["email"]}) == sum(
        1 for entry in listings if entry["email"]
    )
    assert {entry["location"] for entry in listings} <= locations
    # Every listing can be reached: by phone, by email, or both.
    assert all(entry["phone"] or entry["email"] for entry in listings)
    assert all(entry["postcode"] and entry["street_address"] for entry in listings)


async def test_ensure_admin_creates_a_verified_owner_who_can_sign_in(
    client: httpx.AsyncClient, db: AsyncSession
):
    assert await seeding.ensure_admin(db, "boss@example.com", PASSWORD) is True

    admin = await db.scalar(select(User).where(User.email == "boss@example.com"))
    assert admin is not None
    assert (admin.role, admin.staff_role) == (Role.ADMIN, StaffRole.OWNER)
    assert admin.email_verified_at is not None
    login = await client.post(
        "/api/v1/auth/login", json={"email": "boss@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200


async def test_ensure_admin_never_changes_an_existing_account(db: AsyncSession):
    await seeding.ensure_admin(db, "boss@example.com", PASSWORD)

    assert await seeding.ensure_admin(db, "boss@example.com", "Another-pass-1234") is False

    admin = await db.scalar(select(User).where(User.email == "boss@example.com"))
    assert admin is not None
    assert await security.verify_password(PASSWORD, admin.password_hash)
    assert await _count(db, User) == 1


async def test_seed_admin_command_reads_the_environment(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    _with_admin(monkeypatch, None, None)
    assert "not set" in await cli._seed_admin(db)
    assert await _count(db, User) == 0

    _with_admin(monkeypatch, "Boss@Example.com", PASSWORD)
    assert await cli._seed_admin(db) == "Created administrator boss@example.com."
    assert (
        await cli._seed_admin(db)
        == "Administrator boss@example.com already exists; nothing changed."
    )

    # After the first start the password can be removed from the environment.
    _with_admin(monkeypatch, "boss@example.com", None)
    assert "already exists" in await cli._seed_admin(db)
    assert await _count(db, User) == 1


@pytest.mark.parametrize(
    ("email", "password", "message"),
    [
        ("new@example.com", None, "set ADMIN_PASSWORD"),
        ("new@example.com", "short1", "between 10 and 128"),
        ("new@example.com", "onlyletterspassword", "letter and one digit"),
        ("not-an-email", PASSWORD, "email"),
    ],
)
async def test_seed_admin_command_refuses_bad_settings(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    email: str,
    password: str | None,
    message: str,
):
    _with_admin(monkeypatch, email, password)

    with pytest.raises(seeding.SeedingError, match=message):
        await cli._seed_admin(db)
    assert await _count(db, User) == 0
