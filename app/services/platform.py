"""Platform-wide settings the admin edits (Settings): matching, notifications, organisation.

Defaults come from the environment (`MAX_QUOTE_MATCHES`, `SUPPORT_EMAIL`...), so a fresh
install behaves exactly as configured; once an admin saves Settings, the stored values
win. Values are cached per process for a few seconds, so busy endpoints do not query the
table on every request, and the cache is dropped as soon as this process saves.
"""

import time
from typing import Annotated, Self

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import PlatformSetting, User
from app.schemas.common import Email, text

_CACHE_SECONDS = 10.0
_cache: tuple[float, PlatformSettings] | None = None


class LeadMatching(BaseModel):
    # On: requests go to matched installers at once. Off: they wait for the team to choose.
    automatic: bool = True
    max_installers: int = Field(default=5, ge=1, le=20)


class Notifications(BaseModel):
    # Team alerts by email: unmatched or held requests, enquiries for unclaimed listings,
    # contact-form messages and listing claims to check.
    email_alerts: bool = True
    # Reserved: SMS needs a provider (not configured), so it is always off for now.
    sms_alerts: bool = False

    @model_validator(mode="after")
    def _no_sms_provider(self) -> Self:
        if self.sms_alerts:
            raise ValueError("SMS alerts need an SMS provider, which is not set up yet.")
        return self


class Organisation(BaseModel):
    platform_name: str = "PickASparky"
    # Public support address: shown on the website, used as the reply address in emails
    # and where team alerts are sent.
    support_email: str = "hello@pickasparky.co.uk"


class PlatformSettings(BaseModel):
    lead_matching: LeadMatching
    notifications: Notifications
    organisation: Organisation


class OrganisationUpdate(BaseModel):
    platform_name: Annotated[str, text(2, 60)]
    support_email: Email


class PlatformSettingsUpdate(BaseModel):
    """What the Settings page saves (every section, validated strictly)."""

    lead_matching: LeadMatching
    notifications: Notifications
    organisation: OrganisationUpdate


def _defaults() -> PlatformSettings:
    settings = get_settings()
    return PlatformSettings(
        lead_matching=LeadMatching(max_installers=settings.max_quote_matches),
        notifications=Notifications(),
        organisation=Organisation(
            platform_name=settings.email_from_name or "PickASparky",
            support_email=settings.support_email,
        ),
    )


async def load(session: AsyncSession, *, fresh: bool = False) -> PlatformSettings:
    """The current settings: stored values over the environment's defaults."""
    global _cache
    now = time.monotonic()
    if not fresh and _cache is not None and now - _cache[0] < _CACHE_SECONDS:
        return _cache[1]
    values = _defaults().model_dump()
    rows = await session.scalars(select(PlatformSetting))
    for row in rows:
        if row.key in values and isinstance(row.data, dict):
            values[row.key] = {**values[row.key], **row.data}
    try:
        current = PlatformSettings.model_validate(values)
    except ValueError:  # pragma: no cover - stored rows were validated on save
        current = _defaults()
    _cache = (now, current)
    return current


async def save(
    session: AsyncSession, data: PlatformSettingsUpdate, actor: User
) -> PlatformSettings:
    global _cache
    for key, value in data.model_dump(mode="json").items():
        row = await session.get(PlatformSetting, key)
        if row is None:
            session.add(PlatformSetting(key=key, data=value, updated_by_id=actor.id))
        else:
            row.data = value
            row.updated_by_id = actor.id
    await session.commit()
    _cache = None
    return await load(session, fresh=True)


def clear_cache() -> None:
    """Forget the cached settings (used between tests)."""
    global _cache
    _cache = None
