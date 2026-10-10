"""Dashboard support: cookie sessions, password change, admin overview and settings."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Role
from tests.helpers import PASSWORD, auth_headers, create_installer, create_user

AJAX = {"X-Requested-With": "XMLHttpRequest"}


async def test_cookie_session_lifecycle(client: httpx.AsyncClient, db: AsyncSession):
    installer = await create_installer(db, "Cookie Installer")
    login = {"email": "cookie-installer@example.com", "password": PASSWORD}

    # Without the header (e.g. a cross-site form post) the endpoints refuse to work.
    refused = await client.post("/api/v1/auth/session", json=login)
    assert refused.status_code == 401

    started = await client.post("/api/v1/auth/session", json=login, headers=AJAX)
    assert started.status_code == 200, started.text
    body = started.json()
    assert "refresh_token" not in body
    assert body["user"]["installer"]["slug"] == installer.slug
    cookie = started.headers["set-cookie"]
    assert "pas_refresh=" in cookie
    assert "HttpOnly" in cookie
    assert "Path=/api/v1/auth/session" in cookie
    assert "SameSite=lax" in cookie

    refreshed = await client.post("/api/v1/auth/session/refresh", headers=AJAX)
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] != body["access_token"]

    no_header = await client.post("/api/v1/auth/session/refresh")
    assert no_header.status_code == 401

    ended = await client.delete("/api/v1/auth/session", headers=AJAX)
    assert ended.status_code == 204
    after = await client.post("/api/v1/auth/session/refresh", headers=AJAX)
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "invalid_token"


async def test_change_password(client: httpx.AsyncClient, db: AsyncSession):
    user = await create_user(db, email="admin@example.com", role=Role.ADMIN)
    headers = auth_headers(user)
    wrong = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "nope", "new_password": "Brand-new-pass-1"},
        headers=headers,
    )
    assert wrong.status_code == 422
    assert "current_password" in wrong.json()["error"]["fields"]

    changed = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": PASSWORD, "new_password": "Brand-new-pass-1"},
        headers=headers,
    )
    assert changed.status_code == 200
    old = await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": PASSWORD}
    )
    assert old.status_code == 401
    new = await client.post(
        "/api/v1/auth/login", json={"email": "admin@example.com", "password": "Brand-new-pass-1"}
    )
    assert new.status_code == 200


async def test_admin_overview_roles_and_platform(client: httpx.AsyncClient, db: AsyncSession):
    admin = await create_user(db, email="boss@example.com", role=Role.ADMIN)
    installer = await create_installer(db, "Counted Installer")
    headers = auth_headers(admin)

    overview = await client.get("/api/v1/admin/overview", headers=headers)
    assert overview.status_code == 200, overview.text
    data = overview.json()
    assert data["installers_total"] == 1
    assert data["installers_claimed"] == 1
    assert {"key": "pro", "count": 1} in data["installers_by_plan"]
    assert data["locations_total"] > 0

    roles = await client.get("/api/v1/admin/roles", headers=headers)
    assert {role["role"] for role in roles.json()["roles"]} == {"admin", "installer"}

    platform = await client.get("/api/v1/admin/platform", headers=headers)
    assert platform.json()["admins"] == ["boss@example.com"]
    assert "secret" not in platform.text.lower()

    for path in ("overview", "roles", "platform"):
        denied = await client.get(f"/api/v1/admin/{path}", headers=auth_headers(installer.user))
        assert denied.status_code == 403


async def test_admin_location_seo_fields(client: httpx.AsyncClient, db: AsyncSession):
    admin = await create_user(db, role=Role.ADMIN)
    headers = auth_headers(admin)
    updated = await client.patch(
        "/api/v1/admin/locations/manchester",
        json={
            "seo_title": "EV Charger Installers in Manchester | Compare Quotes",
            "seo_description": "Compare vetted Manchester EV charger installers.",
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    public = (await client.get("/api/v1/locations/manchester")).json()
    assert public["seo_title"] == "EV Charger Installers in Manchester | Compare Quotes"
    too_long = await client.patch(
        "/api/v1/admin/locations/manchester", json={"seo_title": "x" * 71}, headers=headers
    )
    assert too_long.status_code == 422
    listing = (await client.get("/api/v1/admin/locations", headers=headers)).json()
    assert all("installer_count" in item for item in listing)
