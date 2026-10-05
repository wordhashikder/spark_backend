"""Password hashing, JWT signing and opaque-token helpers."""

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from anyio import to_thread
from pwdlib import PasswordHash

from app.core.config import get_settings
from app.core.enums import Role

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TYPE = "access"  # noqa: S105 - a claim value, not a credential
REVIEW_INVITE_TOKEN_TYPE = "review_invite"  # noqa: S105 - a claim value, not a credential
REVIEW_INVITE_LIFETIME = timedelta(days=60)

_password_hash = PasswordHash.recommended()
# Verified against when the email is unknown so login takes the same time either way.
_DUMMY_HASH = _password_hash.hash(secrets.token_urlsafe(16))


class TokenError(Exception):
    """A signed token failed verification, expired or has the wrong type."""


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    role: Role


async def hash_password(password: str) -> str:
    """Hash with Argon2id off the event loop (hashing is deliberately CPU-heavy)."""
    return await to_thread.run_sync(_password_hash.hash, password)


async def verify_password(password: str, password_hash: str | None) -> tuple[bool, str | None]:
    """Check a password, returning `(valid, upgraded_hash_or_None)`.

    Passing `None` (unknown account) still performs a full hash verification.
    """
    valid, upgraded = await to_thread.run_sync(
        _password_hash.verify_and_update, password, password_hash or _DUMMY_HASH
    )
    if password_hash is None:
        return False, None
    return valid, upgraded


def generate_opaque_token() -> str:
    """A 256-bit+ random token to hand to the client; only its hash is stored."""
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_ip(ip_address: str) -> str:
    """Keyed hash of an IP address: lets abuse be correlated without storing raw IPs."""
    key = get_settings().secret_key.encode()
    return hmac.new(key, ip_address.encode(), hashlib.sha256).hexdigest()


def _encode(claims: dict[str, Any], lifetime: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {**claims, "iat": now, "exp": now + lifetime}
    return jwt.encode(payload, get_settings().secret_key, algorithm=JWT_ALGORITHM)


def _decode(token: str, expected_type: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            get_settings().secret_key,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "iat", "type"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError from exc
    if payload["type"] != expected_type:
        raise TokenError
    return payload


def create_access_token(user_id: uuid.UUID, role: Role) -> tuple[str, int]:
    """Return `(token, lifetime_in_seconds)`."""
    lifetime = timedelta(minutes=get_settings().access_token_expire_minutes)
    claims = {
        "sub": str(user_id),
        "role": role.value,
        "type": ACCESS_TOKEN_TYPE,
        "jti": uuid.uuid4().hex,
    }
    return _encode(claims, lifetime), int(lifetime.total_seconds())


def decode_access_token(token: str) -> AccessTokenClaims:
    payload = _decode(token, ACCESS_TOKEN_TYPE)
    try:
        return AccessTokenClaims(user_id=uuid.UUID(payload["sub"]), role=Role(payload["role"]))
    except (KeyError, ValueError) as exc:
        raise TokenError from exc


def create_review_invite_token(quote_match_id: uuid.UUID) -> str:
    claims = {"qm": str(quote_match_id), "type": REVIEW_INVITE_TOKEN_TYPE}
    return _encode(claims, REVIEW_INVITE_LIFETIME)


def decode_review_invite_token(token: str) -> uuid.UUID:
    """Return the quote-match id a review invitation was issued for."""
    payload = _decode(token, REVIEW_INVITE_TOKEN_TYPE)
    try:
        return uuid.UUID(payload["qm"])
    except (KeyError, ValueError) as exc:
        raise TokenError from exc
