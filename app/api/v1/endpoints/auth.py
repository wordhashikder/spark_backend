"""Installer and admin authentication.

Two ways to hold a session:
- `/auth/login`, `/auth/refresh`, `/auth/logout`: tokens in the JSON body, for server-side
  clients such as the public website (which keeps them in its own httpOnly cookies).
- `/auth/session`: for the Dashboard app in the browser. The refresh token is set as an
  httpOnly, path-scoped cookie and never reaches JavaScript; the short-lived access token is
  returned in the body and kept in memory. Refreshing requires the `X-Requested-With`
  header, which a cross-site form cannot send and which CORS only allows from the
  configured origins, so the cookie cannot be used for cross-site request forgery.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import CurrentUserDep, EmailQueueDep, GeocoderDep, SessionDep, SettingsDep
from app.core.config import Settings
from app.core.exceptions import NotAuthenticatedError, error_response
from app.core.rate_limit import rate_limit
from app.models import User
from app.schemas.auth import (
    AccessToken,
    ChangePasswordRequest,
    ClaimAccount,
    ClaimPreview,
    EmailRequest,
    LoginRequest,
    Me,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenPair,
    TokenRequest,
)
from app.schemas.common import Message
from app.services import auth, claims

router = APIRouter(prefix="/auth", tags=["auth"])

_CHECK_YOUR_INBOX = Message(
    message="If the details are valid, we have sent an email with the next steps."
)


@router.post(
    "/register",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("register", "5/hour"))],
)
async def register(
    data: RegisterRequest, session: SessionDep, geocoder: GeocoderDep, emails: EmailQueueDep
) -> Message:
    emails.send(await auth.register(session, data, geocoder))
    return _CHECK_YOUR_INBOX


@router.post("/verify-email")
async def verify_email(data: TokenRequest, session: SessionDep) -> Message:
    await auth.verify_email(session, data.token)
    return Message(message="Your email address is confirmed. You can now sign in.")


@router.post(
    "/resend-verification",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("resend-verification", "5/hour"))],
)
async def resend_verification(
    data: EmailRequest, session: SessionDep, emails: EmailQueueDep
) -> Message:
    emails.send(await auth.resend_verification(session, data.email))
    return _CHECK_YOUR_INBOX


@router.post("/login", dependencies=[Depends(rate_limit("login", "10/minute"))])
async def login(data: LoginRequest, session: SessionDep) -> TokenPair:
    return await auth.login(session, data.email, data.password)


@router.post("/refresh")
async def refresh(data: RefreshRequest, session: SessionDep) -> TokenPair:
    return await auth.refresh(session, data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(data: RefreshRequest, session: SessionDep) -> None:
    await auth.logout(session, data.refresh_token)


@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("forgot-password", "5/hour"))],
)
async def forgot_password(
    data: EmailRequest, session: SessionDep, emails: EmailQueueDep
) -> Message:
    emails.send(await auth.forgot_password(session, data.email))
    return _CHECK_YOUR_INBOX


@router.post("/reset-password")
async def reset_password(data: ResetPasswordRequest, session: SessionDep) -> Message:
    await auth.reset_password(session, data.token, data.password)
    return Message(message="Your password has been changed. You can now sign in.")


@router.get("/me")
async def me(user: CurrentUserDep, session: SessionDep) -> Me:
    return await auth.get_profile(session, user)


@router.post("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    user: CurrentUserDep,
    session: SessionDep,
    response: Response,
    settings: SettingsDep,
) -> AccessToken:
    """Change the password. Every session ends; a new one is started for this device."""
    await auth.change_password(session, user, data.current_password, data.new_password)
    tokens = await auth.new_session(session, user)
    _set_refresh_cookie(response, tokens.refresh_token, settings)
    return await _access(session, user, tokens)


# ---- Dashboard sessions (httpOnly refresh cookie) ---------------------------------------

REFRESH_COOKIE = "pas_refresh"
_REFRESH_COOKIE_PATH = "/api/v1/auth/session"
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]
RequestedWith = Annotated[str | None, Header(alias="X-Requested-With")]


def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path=_REFRESH_COOKIE_PATH,
        domain=settings.session_cookie_domain,
        secure=settings.is_production or settings.session_cookie_samesite == "none",
        httponly=True,
        samesite=settings.session_cookie_samesite,
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=_REFRESH_COOKIE_PATH,
        domain=settings.session_cookie_domain,
        secure=settings.is_production or settings.session_cookie_samesite == "none",
        httponly=True,
        samesite=settings.session_cookie_samesite,
    )


async def _access(session: SessionDep, user: User, tokens: TokenPair) -> AccessToken:
    return AccessToken(
        access_token=tokens.access_token,
        expires_in=tokens.expires_in,
        user=await auth.get_profile(session, user),
    )


def _expired_session(settings: Settings) -> JSONResponse:
    """A 401 that also deletes the refresh cookie (a raised error would not carry it)."""
    error = auth.InvalidSessionError()
    response = error_response(401, error.code, error.message, headers=error.headers)
    _clear_refresh_cookie(response, settings)
    return response


def _require_ajax(requested_with: str | None) -> None:
    if requested_with != "XMLHttpRequest":
        raise NotAuthenticatedError("Missing X-Requested-With header.", code="invalid_request")


@router.post("/session", dependencies=[Depends(rate_limit("login", "10/minute"))])
async def start_session(
    data: LoginRequest,
    session: SessionDep,
    response: Response,
    settings: SettingsDep,
    requested_with: RequestedWith = None,
) -> AccessToken:
    """Sign in to the Dashboard."""
    _require_ajax(requested_with)
    tokens = await auth.login(session, data.email, data.password)
    user = await auth.user_for_refresh_token(session, tokens.refresh_token)
    if user is None:  # pragma: no cover - the session was just created
        raise NotAuthenticatedError
    _set_refresh_cookie(response, tokens.refresh_token, settings)
    return await _access(session, user, tokens)


@router.post("/session/refresh", response_model=AccessToken)
async def refresh_session(
    session: SessionDep,
    response: Response,
    settings: SettingsDep,
    refresh_token: RefreshCookie = None,
    requested_with: RequestedWith = None,
) -> AccessToken | JSONResponse:
    """Rotate the refresh cookie and return a new access token."""
    _require_ajax(requested_with)
    if not refresh_token:
        return _expired_session(settings)
    try:
        tokens = await auth.refresh(session, refresh_token)
    except auth.InvalidSessionError:
        return _expired_session(settings)
    user = await auth.user_for_refresh_token(session, tokens.refresh_token)
    if user is None:  # pragma: no cover - the session was just rotated
        return _expired_session(settings)
    _set_refresh_cookie(response, tokens.refresh_token, settings)
    return await _access(session, user, tokens)


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def end_session(
    session: SessionDep,
    response: Response,
    settings: SettingsDep,
    refresh_token: RefreshCookie = None,
    requested_with: RequestedWith = None,
) -> None:
    """Sign out of the Dashboard (idempotent)."""
    _require_ajax(requested_with)
    if refresh_token:
        await auth.logout(session, refresh_token)
    _clear_refresh_cookie(response, settings)


# ---- Claiming a listing ------------------------------------------------------------------


@router.get("/claim", dependencies=[Depends(rate_limit("claim-preview", "30/minute"))])
async def preview_claim(token: str, session: SessionDep) -> ClaimPreview:
    """The listing a claim link is for."""
    installer = await claims.preview(session, token)
    return ClaimPreview(
        business_name=installer.business_name,
        slug=installer.slug,
        email=installer.contact_email or "",
        town=installer.town,
    )


@router.post("/claim", dependencies=[Depends(rate_limit("claim", "10/hour"))])
async def claim_listing(data: ClaimAccount, session: SessionDep) -> Message:
    """Set a password and take over the listing; then sign in as usual."""
    await claims.claim(session, data.token, data.password)
    return Message(message="Your listing is now yours. Sign in to manage it.")
