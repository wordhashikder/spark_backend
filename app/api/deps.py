"""Shared FastAPI dependencies: sessions, external services, authentication and pagination."""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Annotated

from fastapi import BackgroundTasks, Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import Settings, get_settings
from app.core.database import get_session
from app.core.enums import Role
from app.core.exceptions import ForbiddenError, NotAuthenticatedError, NotFoundError
from app.core.rate_limit import client_ip
from app.models import Installer, User
from app.services import installers
from app.services.billing import BillingGateway
from app.services.email import Email, EmailSender
from app.services.geocoding import Geocoder
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


def get_client_ip(request: Request, settings: SettingsDep) -> str:
    return client_ip(request, settings)


GeocoderDep = Annotated[Geocoder, Depends(get_geocoder)]
StorageDep = Annotated[ImageStorage, Depends(get_storage)]
BillingGatewayDep = Annotated[BillingGateway, Depends(get_billing_gateway)]
ClientIpDep = Annotated[str, Depends(get_client_ip)]


class EmailQueue:
    """Queues emails to be sent after the response (and therefore after the commit)."""

    def __init__(
        self,
        background_tasks: BackgroundTasks,
        sender: Annotated[EmailSender, Depends(get_email_sender)],
    ) -> None:
        self._background_tasks = background_tasks
        self._sender = sender

    def send(self, emails: Iterable[Email]) -> None:
        for email in emails:
            self._background_tasks.add_task(self._sender.send, email)


EmailQueueDep = Annotated[EmailQueue, Depends()]


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


async def require_installer(
    session: SessionDep, user: Annotated[User, Depends(require_role(Role.INSTALLER))]
) -> Installer:
    """The signed-in installer's own profile, fully loaded."""
    installer = await installers.get_for_user(session, user.id)
    if installer is None:
        raise NotFoundError("No installer profile exists for this account.")
    return installer


InstallerDep = Annotated[Installer, Depends(require_installer)]
