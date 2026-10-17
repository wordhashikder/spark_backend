"""An admin and an installer can both be signed in to the Dashboard in one browser."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Role
from tests.helpers import PASSWORD, create_installer, create_user

AJAX = {"X-Requested-With": "XMLHttpRequest"}
REFRESH = "/api/v1/auth/session/refresh"


async def _both_signed_in(client: httpx.AsyncClient, db: AsyncSession) -> tuple[str, str]:
    admin = await create_user(db, email="boss@example.com", role=Role.ADMIN)
    installer = await create_installer(db, "Two Roles Electrical")
    for email in (admin.email, installer.user.email):
        started = await client.post(
            "/api/v1/auth/session", json={"email": email, "password": PASSWORD}, headers=AJAX
        )
        assert started.status_code == 200, started.text
    return admin.email, installer.user.email


async def test_each_role_keeps_its_own_cookie(client: httpx.AsyncClient, db: AsyncSession):
    admin_email, installer_email = await _both_signed_in(client, db)
    assert {"pas_dash_admin", "pas_dash_installer"} <= set(client.cookies.keys())

    as_admin = await client.post(f"{REFRESH}?role=admin", headers=AJAX)
    as_installer = await client.post(f"{REFRESH}?role=installer", headers=AJAX)
    assert as_admin.json()["user"]["email"] == admin_email
    assert as_installer.json()["user"]["email"] == installer_email
    # Renewing one never disturbs the other.
    again = await client.post(f"{REFRESH}?role=admin", headers=AJAX)
    assert again.status_code == 200


async def test_without_a_role_two_sessions_are_not_guessed(
    client: httpx.AsyncClient, db: AsyncSession
):
    await _both_signed_in(client, db)
    ambiguous = await client.post(REFRESH, headers=AJAX)
    assert ambiguous.status_code == 401


async def test_a_role_with_no_session_never_borrows_the_other(
    client: httpx.AsyncClient, db: AsyncSession
):
    installer = await create_installer(db, "Only Installer")
    await client.post(
        "/api/v1/auth/session",
        json={"email": installer.user.email, "password": PASSWORD},
        headers=AJAX,
    )
    assert (await client.post(f"{REFRESH}?role=admin", headers=AJAX)).status_code == 401
    # Asked for nothing in particular, the one session there is is used.
    assert (await client.post(REFRESH, headers=AJAX)).status_code == 200


async def test_signing_out_one_role_keeps_the_other(client: httpx.AsyncClient, db: AsyncSession):
    await _both_signed_in(client, db)
    ended = await client.delete("/api/v1/auth/session?role=installer", headers=AJAX)
    assert ended.status_code == 204
    assert (await client.post(f"{REFRESH}?role=installer", headers=AJAX)).status_code == 401
    assert (await client.post(f"{REFRESH}?role=admin", headers=AJAX)).status_code == 200


async def test_the_websites_cookie_name_is_ignored(client: httpx.AsyncClient, db: AsyncSession):
    """The website keeps `pas_refresh` on the same host; the Dashboard must never read it."""
    installer = await create_installer(db, "Website Cookie")
    assert installer.user.email
    client.cookies.set("pas_refresh", "website-token", path="/")
    assert (await client.post(f"{REFRESH}?role=installer", headers=AJAX)).status_code == 401
    assert (await client.post(REFRESH, headers=AJAX)).status_code == 401


async def test_signing_in_again_replaces_the_earlier_session(
    client: httpx.AsyncClient, db: AsyncSession
):
    installer = await create_installer(db, "Signs In Twice")
    login = {"email": installer.user.email, "password": PASSWORD}
    first = await client.post("/api/v1/auth/session", json=login, headers=AJAX)
    old_cookie = client.cookies["pas_dash_installer"]
    assert first.status_code == 200
    await client.post("/api/v1/auth/session", json=login, headers=AJAX)
    assert client.cookies["pas_dash_installer"] != old_cookie
    # The earlier session no longer works anywhere.
    client.cookies.set("pas_dash_installer", old_cookie, path="/api/v1/auth/session")
    assert (await client.post(f"{REFRESH}?role=installer", headers=AJAX)).status_code == 401
