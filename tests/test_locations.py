"""Location pages: coordinates for the local map, and the admin's intro and photo."""

from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Role
from app.models import Location
from app.services import seeding
from tests.helpers import PNG_BYTES, Fakes, auth_headers, create_installer, create_user

SLUG = "cardiff"
_CONTENT = ("intro", "image_url", "image_alt", "image_credit", "image_public_id")


@pytest.fixture
async def cardiff(db: AsyncSession) -> AsyncIterator[None]:
    """Locations survive between tests, so the content edited here is put back afterwards."""
    location = await db.scalar(select(Location).where(Location.slug == SLUG))
    saved = {field: getattr(location, field) for field in _CONTENT}
    yield
    await db.refresh(location)
    for field, value in saved.items():
        setattr(location, field, value)
    await db.commit()


@pytest.fixture
async def admin(db: AsyncSession) -> dict[str, str]:
    return auth_headers(await create_user(db, role=Role.ADMIN))


async def test_locations_carry_coordinates_and_photo_details(client: httpx.AsyncClient):
    listing = (await client.get("/api/v1/locations")).json()
    cardiff = next(item for item in listing if item["slug"] == SLUG)
    assert (cardiff["latitude"], cardiff["longitude"]) == (51.4816, -3.1791)

    manchester = (await client.get("/api/v1/locations/manchester")).json()
    assert manchester["image_url"] == "/images/locations/manchester.jpg"
    assert manchester["image_alt"] == "Modern towers rising above Manchester city centre"
    assert manchester["image_credit"] is None


@pytest.mark.usefixtures("cardiff")
async def test_admin_edits_intro_and_photo_url(client: httpx.AsyncClient, admin: dict[str, str]):
    url = f"/api/v1/admin/locations/{SLUG}"
    response = await client.patch(
        url,
        headers=admin,
        json={
            "intro": "Cardiff is growing its charging network.",
            "image_url": "https://res.cloudinary.com/demo/image/upload/cardiff.jpg",
            "image_alt": "Cardiff Bay at dusk",
            "image_credit": "Photo: Jane Doe",
        },
    )
    assert response.status_code == 200

    public = (await client.get(f"/api/v1/locations/{SLUG}")).json()
    assert public["intro"] == "Cardiff is growing its charging network."
    assert public["image_alt"] == "Cardiff Bay at dusk"
    assert public["image_credit"] == "Photo: Jane Doe"

    # Only the fields sent are changed; null clears one.
    cleared = await client.patch(url, headers=admin, json={"image_credit": None})
    assert cleared.json()["image_credit"] is None
    assert cleared.json()["image_alt"] == "Cardiff Bay at dusk"

    for bad in ("http://insecure.example/x.jpg", "//cdn.example/x.jpg", "javascript:alert(1)"):
        invalid = await client.patch(url, headers=admin, json={"image_url": bad})
        assert invalid.status_code == 422, bad
    assert (await client.patch(url, headers=admin, json={})).status_code == 422
    assert (
        await client.patch(
            "/api/v1/admin/locations/atlantis", headers=admin, json={"intro": "Nope."}
        )
    ).status_code == 404


@pytest.mark.usefixtures("cardiff")
async def test_admin_uploads_replaces_and_removes_the_photo(
    client: httpx.AsyncClient, fakes: Fakes, admin: dict[str, str]
):
    url = f"/api/v1/admin/locations/{SLUG}/image"
    files = {"file": ("cardiff.png", PNG_BYTES, "image/png")}

    first = await client.post(url, headers=admin, files=files)
    assert first.status_code == 200
    assert first.json()["image_url"] == "https://images.test/locations/image-1.png"
    assert first.json()["image_alt"] == "Cardiff, Wales"

    second = await client.post(
        url, headers=admin, files=files, data={"alt": "Cardiff Castle", "credit": "Photo: A. N."}
    )
    assert (second.json()["image_alt"], second.json()["image_credit"]) == (
        "Cardiff Castle",
        "Photo: A. N.",
    )
    assert fakes.storage.deleted == ["locations/image-1"]

    # Pointing the page at another URL releases the uploaded photo too.
    await client.patch(
        f"/api/v1/admin/locations/{SLUG}",
        headers=admin,
        json={"image_url": "/images/locations/cardiff.jpg"},
    )
    assert fakes.storage.deleted == ["locations/image-1", "locations/image-2"]

    removed = await client.delete(url, headers=admin)
    assert removed.status_code == 200
    assert removed.json()["image_url"] is None
    assert (await client.get(f"/api/v1/locations/{SLUG}")).json()["image_url"] is None


@pytest.mark.usefixtures("cardiff")
async def test_seeding_never_overwrites_the_admins_content(
    client: httpx.AsyncClient, db: AsyncSession, admin: dict[str, str]
):
    await client.patch(
        f"/api/v1/admin/locations/{SLUG}", headers=admin, json={"intro": "Written by the admin."}
    )
    await seeding.seed_locations(db)
    assert (await client.get(f"/api/v1/locations/{SLUG}")).json()["intro"] == (
        "Written by the admin."
    )


@pytest.mark.usefixtures("cardiff")
async def test_seed_refreshes_bundled_photos_but_keeps_uploaded_ones(db: AsyncSession):
    location = await db.scalar(select(Location).where(Location.slug == SLUG))
    bundled = ("/images/locations/cardiff.jpg", "Cardiff shopping street hung with Welsh flags")
    assert (location.image_url, location.image_alt) == bundled

    # No photo, or an older photo shipped with the site: the current bundled photo is used.
    for url in (None, "/images/locations/cardiff-old.jpg"):
        location.image_url, location.image_alt = url, "Out of date"
        await db.commit()
        await seeding.seed_locations(db)
        await db.refresh(location)
        assert (location.image_url, location.image_alt) == bundled

    # A photo the admin uploaded is never replaced.
    uploaded = ("https://res.cloudinary.com/demo/image/upload/cardiff.jpg", "Cardiff Bay")
    location.image_url, location.image_alt = uploaded
    await db.commit()
    await seeding.seed_locations(db)
    await db.refresh(location)
    assert (location.image_url, location.image_alt) == uploaded


def test_location_data_gives_each_directory_slot_to_one_town(monkeypatch: pytest.MonkeyPatch):
    def town(slug: str, column: str | None, position: int | None) -> dict[str, object]:
        return {
            "slug": slug,
            "name": slug.title(),
            "region": "North West",
            "latitude": 53.5,
            "longitude": -2.2,
            "directory_column": column,
            "directory_position": position,
        }

    shared_slot = [town("salford", "nearby", 1), town("trafford", "nearby", 1)]
    monkeypatch.setattr(seeding, "_load", lambda _name: shared_slot)
    with pytest.raises(seeding.SeedingError, match="invalid directory position"):
        seeding._location_rows()

    listed_twice = [town("salford", "nearby", 1), town("salford", "other", 2)]
    monkeypatch.setattr(seeding, "_load", lambda _name: listed_twice)
    with pytest.raises(seeding.SeedingError, match="listed twice"):
        seeding._location_rows()


async def test_only_admins_manage_locations(client: httpx.AsyncClient, db: AsyncSession):
    installer = await create_installer(db, "Pro Manchester")
    headers = auth_headers(installer.user)
    assert (await client.get("/api/v1/admin/locations", headers=headers)).status_code == 403
    assert (await client.get("/api/v1/admin/locations")).status_code == 401
