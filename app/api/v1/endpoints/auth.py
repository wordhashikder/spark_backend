"""Installer and admin authentication."""

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUserDep, EmailQueueDep, GeocoderDep, SessionDep
from app.core.rate_limit import rate_limit
from app.schemas.auth import (
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
from app.services import auth

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
