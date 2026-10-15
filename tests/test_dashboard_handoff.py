"""Website sign-in carried into the Dashboard with a one-time code."""

from urllib.parse import parse_qs, urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import auth_headers, create_installer, create_user

AJAX = {"X-Requested-With": "XMLHttpRequest"}


async def _code(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post("/api/v1/auth/dashboard-handoff", headers=headers)
    assert response.status_code == 200
    url = urlparse(response.json()["url"])
    assert url.path == "/sso"
    return parse_qs(url.query)["code"][0]


async def test_handoff_signs_an_installer_into_the_dashboard(
    client: httpx.AsyncClient, db: AsyncSession
):
    installer = await create_installer(db, "Handoff Electrical")
    user = installer.user
    code = await _code(client, auth_headers(user))

    opened = await client.post("/api/v1/auth/session/handoff", json={"token": code}, headers=AJAX)
    assert opened.status_code == 200
    assert opened.json()["user"]["email"] == user.email
    assert "pas_refresh" in opened.headers["set-cookie"]
    assert "HttpOnly" in opened.headers["set-cookie"]

    # The session works: the refresh cookie renews it.
    renewed = await client.post("/api/v1/auth/session/refresh", headers=AJAX)
    assert renewed.status_code == 200


async def test_handoff_code_works_once(client: httpx.AsyncClient, db: AsyncSession):
    user = await create_user(db)
    code = await _code(client, auth_headers(user))
    first = await client.post("/api/v1/auth/session/handoff", json={"token": code}, headers=AJAX)
    again = await client.post("/api/v1/auth/session/handoff", json={"token": code}, headers=AJAX)
    assert first.status_code == 200
    assert again.status_code >= 400


async def test_handoff_needs_a_session_and_the_ajax_header(
    client: httpx.AsyncClient, db: AsyncSession
):
    assert (await client.post("/api/v1/auth/dashboard-handoff")).status_code == 401
    user = await create_user(db)
    code = await _code(client, auth_headers(user))
    no_header = await client.post("/api/v1/auth/session/handoff", json={"token": code})
    assert no_header.status_code == 401
    wrong = await client.post(
        "/api/v1/auth/session/handoff", json={"token": "x" * 43}, headers=AJAX
    )
    assert wrong.status_code >= 400


async def test_disabled_account_cannot_use_a_handoff_code(
    client: httpx.AsyncClient, db: AsyncSession
):
    user = await create_user(db)
    code = await _code(client, auth_headers(user))
    user.is_active = False
    await db.commit()
    opened = await client.post("/api/v1/auth/session/handoff", json={"token": code}, headers=AJAX)
    assert opened.status_code >= 400
