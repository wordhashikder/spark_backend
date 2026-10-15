"""Shared FastAPI dependencies: sessions, external services, authentication and pagination."""

import dataclasses
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Annotated

from fastapi import BackgroundTasks, Depends, Query, Request, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import permissions, security
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.core.enums import Role, StaffRole
from app.core.exceptions import ForbiddenError, NotAuthenticatedError, NotFoundError
from app.core.middleware import MAX_UPLOAD_BYTES
from app.core.rate_limit import client_ip
from app.models import Customer, Installer, User
from app.services import customers, installers, platform
from app.services.access import access_for
from app.services.billing import BillingGateway
from app.services.email import Email, EmailSender
from app.services.geocoding import Geocoder
from app.services.revalidation import Revalidator
from app.services.storage import ImageStorage

DEFAULT_PAGE_SIZE = 12
MAX_PAGE_SIZE = 100

_bearer = HTTPBearer(auto_error=False, description="Access token from `POST /auth/login`.")

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_geocoder(request: Request) -> Geocoder:
    return request.app.state.geocoder


def get_email_sender(request: Request) -> EmailSender:
    return request.app.state.email_sender


def get_storage(request: Request) -> ImageStorage:
    return request.app.state.storage


def get_billing_gateway(request: Request) -> BillingGateway:
    return request.app.state.billing_gateway


def get_revalidator(request: Request) -> Revalidator:
    return request.app.state.revalidator


class CacheRefresh:
    """Refreshes the website's cached pages for some tags after the response is sent."""

    def __init__(
        self,
        background_tasks: BackgroundTasks,
        revalidator: Annotated[Revalidator, Depends(get_revalidator)],
    ) -> None:
        self._background_tasks = background_tasks
        self._revalidator = revalidator

    def __call__(self, *tags: str) -> None:
        self._background_tasks.add_task(self._revalidator.revalidate, list(tags))


def get_client_ip(request: Request, settings: SettingsDep) -> str:
    return client_ip(request, settings)


GeocoderDep = Annotated[Geocoder, Depends(get_geocoder)]
StorageDep = Annotated[ImageStorage, Depends(get_storage)]
BillingGatewayDep = Annotated[BillingGateway, Depends(get_billing_gateway)]
ClientIpDep = Annotated[str, Depends(get_client_ip)]
CacheRefreshDep = Annotated[CacheRefresh, Depends()]


async def get_platform_settings(session: SessionDep) -> platform.PlatformSettings:
    return await platform.load(session)


PlatformSettingsDep = Annotated[platform.PlatformSettings, Depends(get_platform_settings)]


class EmailQueue:
    """Queues emails to be sent after the response (and therefore after the commit).

    Applies the Settings page on the way out: the platform name as the sender, the support
    address for team alerts (dropped while email alerts are off) and as the address shown
    in every email.
    """

    def __init__(
        self,
        background_tasks: BackgroundTasks,
        sender: Annotated[EmailSender, Depends(get_email_sender)],
        settings: PlatformSettingsDep,
    ) -> None:
        self._background_tasks = background_tasks
        self._sender = sender
        self._settings = settings

    def send(self, emails: Iterable[Email]) -> None:
        organisation = self._settings.organisation
        for email in emails:
            if email.team and not self._settings.notifications.email_alerts:
                continue
            prepared = dataclasses.replace(
                email,
                to=organisation.support_email if email.team else email.to,
                from_name=email.from_name or organisation.platform_name,
                context={"support_email": organisation.support_email, **email.context},
            )
            self._background_tasks.add_task(self._sender.send, prepared)


EmailQueueDep = Annotated[EmailQueue, Depends()]


async def read_upload(file: UploadFile) -> bytes:
    """Read at most one byte past the limit, so an oversized file is detected, not buffered."""
    return await file.read(MAX_UPLOAD_BYTES + 1)


@dataclass(frozen=True, slots=True)
class Page:
    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def get_page(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> Page:
    return Page(page=page, page_size=page_size)


PageDep = Annotated[Page, Depends(get_page)]


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """Resolve the bearer access token to an active user."""
    if credentials is None:
        raise NotAuthenticatedError
    try:
        claims = security.decode_access_token(credentials.credentials)
    except security.TokenError as exc:
        raise NotAuthenticatedError(
            "Your session has expired. Please sign in again.", code="invalid_token"
        ) from exc
    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise NotAuthenticatedError(
            "Your session has expired. Please sign in again.", code="invalid_token"
        )
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def require_role(role: Role) -> Callable[[User], Awaitable[User]]:
    """Dependency factory: the current user must hold `role`."""

    async def check(user: CurrentUserDep) -> User:
        if user.role is not role:
            raise ForbiddenError
        return user

    return check


AdminDep = Annotated[User, Depends(require_role(Role.ADMIN))]

_ADMIN_PATH_MARKER = "/admin/"


async def require_admin_access(request: Request, session: SessionDep, user: CurrentUserDep) -> User:
    """The signed-in team member may use the back-office area this request belongs to.

    The area (module) comes from the path (see `app/core/permissions.py`); the role matrix
    decides. The modules the member may use are left on `request.state.access`.
    """
    if user.role is not Role.ADMIN:
        raise ForbiddenError
    access = await access_for(session, user.staff_role)
    path = request.url.path.split(_ADMIN_PATH_MARKER, 1)[-1]
    modules = permissions.modules_for_path(path)
    allowed = user.staff_role is StaffRole.OWNER if modules is None else bool(modules & access)
    if not allowed:
        raise ForbiddenError(
            "Your role does not include this part of the dashboard.", code="module_forbidden"
        )
    request.state.access = access
    return user


StaffDep = Annotated[User, Depends(require_admin_access)]


def get_access(request: Request) -> frozenset[str]:
    """The modules the signed-in team member may use (set by `require_admin_access`)."""
    return getattr(request.state, "access", frozenset())


AccessDep = Annotated[frozenset[str], Depends(get_access)]


async def require_installer(
    session: SessionDep, user: Annotated[User, Depends(require_role(Role.INSTALLER))]
) -> Installer:
    """The signed-in installer's own profile, fully loaded."""
    installer = await installers.get_for_user(session, user.id)
    if installer is None:
        raise NotFoundError("No installer profile exists for this account.")
    return installer


InstallerDep = Annotated[Installer, Depends(require_installer)]


async def get_current_customer(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Customer:
    """Resolve the customer's session token (sent by the website's server) to a customer."""
    if credentials is None:
        raise NotAuthenticatedError("Please request a new link to sign in.", code="invalid_token")
    return await customers.authenticate(session, credentials.credentials)


CurrentCustomerDep = Annotated[Customer, Depends(get_current_customer)]
