"""Account use cases: registration, email verification, sessions and password reset."""

import logging
import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import get_settings
from app.core.enums import AuthTokenPurpose, Role
from app.core.exceptions import (
    FieldValidationError,
    ForbiddenError,
    InvalidTokenError,
    NotAuthenticatedError,
)
from app.models import AuthToken, RefreshToken, User
from app.models.base import utcnow
from app.schemas.auth import Me, MeInstaller, RegisterRequest, TokenPair
from app.services import email as emails
from app.services import installers
from app.services.email import Email
from app.services.geocoding import Geocoder

logger = logging.getLogger(__name__)

VERIFICATION_LIFETIME = timedelta(hours=48)
PASSWORD_RESET_LIFETIME = timedelta(hours=1)


class InvalidCredentialsError(NotAuthenticatedError):
    code = "invalid_credentials"
    message = "Incorrect email or password."


class InvalidSessionError(NotAuthenticatedError):
    code = "invalid_token"
    message = "Your session has expired. Please sign in again."


class EmailNotVerifiedError(ForbiddenError):
    code = "email_not_verified"
    message = "Please confirm your email address before signing in."


class AccountDisabledError(ForbiddenError):
    code = "account_disabled"
    message = "This account has been disabled."


async def register(session: AsyncSession, data: RegisterRequest, geocoder: Geocoder) -> list[Email]:
    """Create an unverified installer account.

    Returns the email to send: a verification link, or an "account exists" notice when the
    address is already registered, so the response never reveals which was the case.
    """
    place = await installers.geocode_or_field_error(geocoder, data.postcode, "postcode")
    password_hash = await security.hash_password(data.password)
    if await _user_by_email(session, data.email) is not None:
        return [emails.account_exists(data.email)]

    user = User(email=data.email, password_hash=password_hash, role=Role.INSTALLER)
    try:
        session.add(user)
        await installers.create(
            session,
            user=user,
            business_name=data.business_name,
            contact_name=data.contact_name,
            phone=data.phone,
            requested_plan=data.plan,
            place=place,
        )
        await session.flush()
    except IntegrityError:
        # Lost a race with a concurrent registration for the same email address.
        await session.rollback()
        if await _user_by_email(session, data.email) is None:
            raise
        return [emails.account_exists(data.email)]

    token = await _issue_auth_token(
        session, user, AuthTokenPurpose.VERIFY_EMAIL, VERIFICATION_LIFETIME
    )
    await session.commit()
    return [emails.verify_email(user.email, data.contact_name, token)]


async def verify_email(session: AsyncSession, token: str) -> None:
    user = await _consume_auth_token(session, token, AuthTokenPurpose.VERIFY_EMAIL)
    user.email_verified_at = user.email_verified_at or utcnow()
    await session.commit()


async def resend_verification(session: AsyncSession, email: str) -> list[Email]:
    user = await _user_by_email(session, email)
    if user is None or not user.is_active or user.email_verified_at is not None:
        return []
    installer = await installers.get_for_user(session, user.id)
    token = await _issue_auth_token(
        session, user, AuthTokenPurpose.VERIFY_EMAIL, VERIFICATION_LIFETIME
    )
    await session.commit()
    contact_name = installer.contact_name if installer else "there"
    return [emails.verify_email(user.email, contact_name, token)]


async def login(session: AsyncSession, email: str, password: str) -> TokenPair:
    user = await _user_by_email(session, email)
    valid, upgraded_hash = await security.verify_password(
        password, user.password_hash if user else None
    )
    if user is None or not valid:
        raise InvalidCredentialsError
    if not user.is_active:
        raise AccountDisabledError
    if user.email_verified_at is None:
        raise EmailNotVerifiedError

    if upgraded_hash is not None:
        user.password_hash = upgraded_hash
    user.last_login_at = utcnow()
    tokens = await _start_session(session, user, family_id=uuid.uuid4())
    await session.commit()
    return tokens


async def refresh(session: AsyncSession, refresh_token: str) -> TokenPair:
    """Rotate a refresh token. Presenting a revoked one revokes its whole family."""
    stored = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == security.hash_token(refresh_token))
        .with_for_update()
    )
    if stored is None:
        raise InvalidSessionError
    if stored.revoked_at is not None:
        logger.warning("Refresh token reuse detected; revoking family %s", stored.family_id)
        await _revoke_family(session, stored.family_id)
        await session.commit()
        raise InvalidSessionError

    user = await session.get(User, stored.user_id)
    if stored.expires_at <= utcnow() or user is None or not user.is_active:
        await _revoke_family(session, stored.family_id)
        await session.commit()
        raise InvalidSessionError

    tokens = await _start_session(session, user, family_id=stored.family_id, replaces=stored)
    await session.commit()
    return tokens


async def logout(session: AsyncSession, refresh_token: str) -> None:
    """End the session the token belongs to; unknown tokens are ignored (idempotent)."""
    family_id = await session.scalar(
        select(RefreshToken.family_id).where(
            RefreshToken.token_hash == security.hash_token(refresh_token)
        )
    )
    if family_id is not None:
        await _revoke_family(session, family_id)
        await session.commit()


async def forgot_password(session: AsyncSession, email: str) -> list[Email]:
    user = await _user_by_email(session, email)
    if user is None or not user.is_active:
        return []
    token = await _issue_auth_token(
        session, user, AuthTokenPurpose.RESET_PASSWORD, PASSWORD_RESET_LIFETIME
    )
    await session.commit()
    return [emails.password_reset(user.email, token)]


async def reset_password(session: AsyncSession, token: str, password: str) -> None:
    """Set a new password and sign the user out everywhere.

    Following the emailed link also proves control of the mailbox, so it verifies the address.
    """
    user = await _consume_auth_token(session, token, AuthTokenPurpose.RESET_PASSWORD)
    user.password_hash = await security.hash_password(password)
    user.email_verified_at = user.email_verified_at or utcnow()
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    await session.commit()


async def change_password(
    session: AsyncSession, user: User, current_password: str, new_password: str
) -> None:
    """Change the password after checking the current one; ends every other session."""
    valid, _ = await security.verify_password(current_password, user.password_hash)
    if not valid:
        raise FieldValidationError({"current_password": "Your current password is incorrect."})
    user.password_hash = await security.hash_password(new_password)
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    await session.commit()


async def new_session(session: AsyncSession, user: User) -> TokenPair:
    """Start a fresh session for a signed-in user (e.g. after changing the password)."""
    tokens = await _start_session(session, user, family_id=uuid.uuid4())
    await session.commit()
    return tokens


async def user_for_refresh_token(session: AsyncSession, refresh_token: str) -> User | None:
    user_id = await session.scalar(
        select(RefreshToken.user_id).where(
            RefreshToken.token_hash == security.hash_token(refresh_token)
        )
    )
    return await session.get(User, user_id) if user_id else None


async def get_profile(session: AsyncSession, user: User) -> Me:
    installer = await installers.get_for_user(session, user.id)
    return Me(
        id=user.id,
        email=user.email,
        role=user.role,
        email_verified=user.email_verified_at is not None,
        installer=MeInstaller(
            slug=installer.slug,
            business_name=installer.business_name,
            status=installer.status,
            plan=installer.plan,
            subscription_status=installer.subscription_status,
        )
        if installer
        else None,
    )


async def _user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email))


async def _start_session(
    session: AsyncSession,
    user: User,
    *,
    family_id: uuid.UUID,
    replaces: RefreshToken | None = None,
) -> TokenPair:
    """Issue an access token and a new refresh token in `family_id` (the caller commits)."""
    settings = get_settings()
    raw_refresh_token = security.generate_opaque_token()
    stored = RefreshToken(
        id=uuid.uuid7(),
        user_id=user.id,
        token_hash=security.hash_token(raw_refresh_token),
        family_id=family_id,
        expires_at=utcnow() + timedelta(days=settings.refresh_token_expire_days),
    )
    session.add(stored)
    if replaces is not None:
        # The self-referencing foreign key needs the new row to exist first; without a
        # mapped relationship the unit of work does not order these two writes for us.
        await session.flush()
        replaces.revoked_at = utcnow()
        replaces.replaced_by = stored.id
    access_token, expires_in = security.create_access_token(user.id, user.role)
    return TokenPair(
        access_token=access_token, refresh_token=raw_refresh_token, expires_in=expires_in
    )


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


async def _issue_auth_token(
    session: AsyncSession, user: User, purpose: AuthTokenPurpose, lifetime: timedelta
) -> str:
    """Create a single-use token, retiring any earlier unused one for the same purpose."""
    now = utcnow()
    await session.execute(
        update(AuthToken)
        .where(
            AuthToken.user_id == user.id,
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    raw_token = security.generate_opaque_token()
    session.add(
        AuthToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=security.hash_token(raw_token),
            expires_at=now + lifetime,
        )
    )
    return raw_token


async def _consume_auth_token(session: AsyncSession, token: str, purpose: AuthTokenPurpose) -> User:
    """Mark a valid token as used and return its user; raise `InvalidTokenError` otherwise."""
    stored = await session.scalar(
        select(AuthToken)
        .where(AuthToken.token_hash == security.hash_token(token), AuthToken.purpose == purpose)
        .with_for_update()
    )
    now = utcnow()
    if stored is None or stored.used_at is not None or stored.expires_at <= now:
        raise InvalidTokenError
    user = await session.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise InvalidTokenError
    stored.used_at = now
    return user
