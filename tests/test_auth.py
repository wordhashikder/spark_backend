"""Registration, verification, sessions and password reset."""

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.enums import Role
from app.models import Installer, RefreshToken, User
from tests.helpers import PASSWORD, Fakes, auth_headers, create_installer, create_user

REGISTRATION = {
    "email": "Owner@Example.com",
    "password": PASSWORD,
    "business_name": "Bright Sparks Ltd",
    "contact_name": "Jo Bright",
    "phone": "0161 496 0001",
    "postcode": "m11aa",
    "plan": "pro",
    "accept_terms": True,
}


async def _login(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> httpx.Response:
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def test_register_verify_login_and_me(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    registered = await client.post("/api/v1/auth/register", json=REGISTRATION)
    assert registered.status_code == 202
    assert set(registered.json()) == {"message"}

    [email] = fakes.emails.sent
    assert (email.template, email.to) == ("verify_email", "owner@example.com")
    assert email.context["link"].startswith("https://frontend.test/installer/verify-email?token=")

    blocked = await _login(client, "owner@example.com")
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "email_not_verified"

    token = fakes.emails.token_from("verify_email")
    verified = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert verified.status_code == 200
    reused = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert reused.status_code == 400
    assert reused.json()["error"]["code"] == "invalid_token"

    logged_in = await _login(client, " OWNER@example.com ")
    assert logged_in.status_code == 200
    tokens = logged_in.json()
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == 15 * 60
    claims = security.decode_access_token(tokens["access_token"])
    assert claims.role is Role.INSTALLER

    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    assert me.headers["Cache-Control"] == "no-store"
    assert me.json() == {
        "id": str(claims.user_id),
        "email": "owner@example.com",
        "role": "installer",
        "email_verified": True,
        "installer": {
            "slug": "bright-sparks-ltd",
            "business_name": "Bright Sparks Ltd",
            "status": "pending",
            "plan": "free",
            "subscription_status": "none",
        },
    }

    installer = await db.scalar(select(Installer))
    assert installer.requested_plan == "pro"
    assert installer.base_postcode == "M1 1AA"
    assert installer.town == "Manchester"
    assert (installer.latitude, installer.longitude) == (53.4808, -2.2426)
    user = await db.get(User, claims.user_id)
    assert user.password_hash.startswith("$argon2id$")
    assert user.last_login_at is not None


async def test_refresh_rotates_and_reuse_revokes_the_family(
    client: httpx.AsyncClient, db: AsyncSession
):
    user = await create_user(db)
    first = (await _login(client, user.email)).json()

    rotated = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert rotated.status_code == 200
    second = rotated.json()
    assert second["refresh_token"] != first["refresh_token"]
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {second['access_token']}"}
    )
    assert me.status_code == 200

    stored = (await db.scalars(select(RefreshToken).order_by(RefreshToken.created_at))).all()
    assert len({token.family_id for token in stored}) == 1
    assert stored[0].replaced_by == stored[1].id
    assert stored[0].token_hash == security.hash_token(first["refresh_token"])

    replayed = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
    )
    assert replayed.status_code == 401
    assert replayed.json()["error"]["code"] == "invalid_token"

    # The legitimate holder of the newest token is signed out too.
    after_reuse = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}
    )
    assert after_reuse.status_code == 401
    active = await db.scalar(
        select(func.count()).select_from(RefreshToken).where(RefreshToken.revoked_at.is_(None))
    )
    assert active == 0


async def test_unknown_refresh_token_is_rejected(client: httpx.AsyncClient):
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": "nope"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


async def test_logout_ends_the_session_and_is_idempotent(
    client: httpx.AsyncClient, db: AsyncSession
):
    user = await create_user(db)
    tokens = (await _login(client, user.email)).json()
    body = {"refresh_token": tokens["refresh_token"]}

    assert (await client.post("/api/v1/auth/logout", json=body)).status_code == 204
    assert (await client.post("/api/v1/auth/refresh", json=body)).status_code == 401
    assert (await client.post("/api/v1/auth/logout", json=body)).status_code == 204
    unknown = await client.post("/api/v1/auth/logout", json={"refresh_token": "never-issued"})
    assert unknown.status_code == 204


async def test_duplicate_registration_does_not_reveal_the_account(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    first = await client.post("/api/v1/auth/register", json=REGISTRATION)
    second = await client.post(
        "/api/v1/auth/register", json=REGISTRATION | {"business_name": "Someone Else"}
    )
    assert (first.status_code, first.json()) == (second.status_code, second.json())

    assert [email.template for email in fakes.emails.sent] == ["verify_email", "account_exists"]
    assert fakes.emails.sent[1].to == "owner@example.com"
    assert await db.scalar(select(func.count()).select_from(User)) == 1
    assert await db.scalar(select(func.count()).select_from(Installer)) == 1


@pytest.mark.parametrize(
    "password", ["Short1", "nodigitsinthispassword", "1234567890123", "a1" * 65]
)
async def test_password_policy(client: httpx.AsyncClient, password: str):
    response = await client.post(
        "/api/v1/auth/register", json=REGISTRATION | {"password": password}
    )
    assert response.status_code == 422
    assert "password" in response.json()["error"]["fields"]


async def test_registration_validation(client: httpx.AsyncClient, fakes: Fakes):
    unknown_postcode = await client.post(
        "/api/v1/auth/register", json=REGISTRATION | {"postcode": "ZZ9 9ZZ"}
    )
    assert unknown_postcode.status_code == 422
    assert unknown_postcode.json()["error"]["fields"] == {
        "postcode": "We could not find that postcode."
    }

    invalid = await client.post(
        "/api/v1/auth/register",
        json=REGISTRATION | {"accept_terms": False, "phone": "12345", "plan": "gold"},
    )
    assert invalid.status_code == 422
    assert set(invalid.json()["error"]["fields"]) == {"accept_terms", "phone", "plan"}

    fakes.geocoder.unavailable = True
    down = await client.post("/api/v1/auth/register", json=REGISTRATION)
    assert down.status_code == 503
    assert down.json()["error"]["code"] == "geocoding_unavailable"
    assert fakes.emails.sent == []


async def test_business_slugs_are_deduplicated_and_never_shadow_routes(
    client: httpx.AsyncClient, db: AsyncSession
):
    for index, name in enumerate(["Volt & Co", "Volt Co", "Volt-Co!", "Me"]):
        payload = REGISTRATION | {"email": f"owner{index}@example.com", "business_name": name}
        assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 202
    slugs = (await db.scalars(select(Installer.slug).order_by(Installer.created_at))).all()
    assert slugs == ["volt-co", "volt-co-2", "volt-co-3", "me-2"]


async def test_login_failures_are_indistinguishable(client: httpx.AsyncClient, db: AsyncSession):
    user = await create_user(db)
    wrong_password = await _login(client, user.email, "Wrong-password-1")
    unknown_email = await _login(client, "ghost@example.com")
    malformed_email = await _login(client, "not-an-email")
    for response in (wrong_password, unknown_email, malformed_email):
        assert response.status_code == 401
        assert response.json() == wrong_password.json()
    assert wrong_password.json()["error"]["code"] == "invalid_credentials"
    assert wrong_password.headers["WWW-Authenticate"] == "Bearer"


async def test_disabled_account_cannot_sign_in_or_use_tokens(
    client: httpx.AsyncClient, db: AsyncSession
):
    user = await create_user(db, active=False)
    response = await _login(client, user.email)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_disabled"
    me = await client.get("/api/v1/auth/me", headers=auth_headers(user))
    assert me.status_code == 401


async def test_forgot_and_reset_password_revokes_sessions(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    user = await create_user(db)
    session_tokens = (await _login(client, user.email)).json()

    known = await client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    unknown = await client.post("/api/v1/auth/forgot-password", json={"email": "ghost@example.com"})
    assert (known.status_code, known.json()) == (202, unknown.json())
    assert unknown.status_code == 202
    [email] = fakes.emails.sent
    assert email.template == "password_reset"
    assert email.context["link"].startswith("https://frontend.test/installer/reset-password?token=")

    token = fakes.emails.token_from("password_reset")
    weak = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": "weak"}
    )
    assert weak.status_code == 422

    new_password = "Brand-new-pass-99"
    reset = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": new_password}
    )
    assert reset.status_code == 200
    replay = await client.post(
        "/api/v1/auth/reset-password", json={"token": token, "password": new_password}
    )
    assert replay.status_code == 400
    assert replay.json()["error"]["code"] == "invalid_token"

    assert (await _login(client, user.email)).status_code == 401
    assert (await _login(client, user.email, new_password)).status_code == 200
    stale = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": session_tokens["refresh_token"]}
    )
    assert stale.status_code == 401


async def test_a_newer_reset_link_retires_the_older_one(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    user = await create_user(db)
    await client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    older = fakes.emails.token_from("password_reset")
    await client.post("/api/v1/auth/forgot-password", json={"email": user.email})

    response = await client.post(
        "/api/v1/auth/reset-password", json={"token": older, "password": "Brand-new-pass-99"}
    )
    assert response.status_code == 400


async def test_resend_verification(client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession):
    await client.post("/api/v1/auth/register", json=REGISTRATION)
    original = fakes.emails.token_from("verify_email")
    verified_user = await create_user(db)

    for email in ("owner@example.com", verified_user.email, "ghost@example.com"):
        response = await client.post("/api/v1/auth/resend-verification", json={"email": email})
        assert response.status_code == 202
    assert [email.to for email in fakes.emails.of("verify_email")] == ["owner@example.com"] * 2

    stale = await client.post("/api/v1/auth/verify-email", json={"token": original})
    assert stale.status_code == 400
    fresh = await client.post(
        "/api/v1/auth/verify-email", json={"token": fakes.emails.token_from("verify_email")}
    )
    assert fresh.status_code == 200


async def test_me_requires_a_valid_access_token(client: httpx.AsyncClient, db: AsyncSession):
    missing = await client.get("/api/v1/auth/me")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "not_authenticated"

    installer = await create_installer(db, "Token Test")
    wrong_type = security.create_review_invite_token(installer.id)
    for token in ("garbage", wrong_type):
        response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_token"

    admin = await create_user(db, role=Role.ADMIN)
    me = await client.get("/api/v1/auth/me", headers=auth_headers(admin))
    assert me.json()["role"] == "admin"
    assert me.json()["installer"] is None
