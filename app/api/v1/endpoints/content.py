"""Public website content: the text of each page, and the organisation's details.

The website caches these responses and the Dashboard refreshes the cache whenever the team
saves, so edits appear within seconds without a deploy.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import PlatformSettingsDep, SessionDep
from app.schemas.content import PublicContent
from app.services import content

router = APIRouter(tags=["content"])


class PublicPlatform(BaseModel):
    platform_name: str
    support_email: str


@router.get("/content/{key}")
async def get_content(key: str, session: SessionDep) -> PublicContent:
    """A page's content: the team's version, or the original wording."""
    return await content.public(session, key)


@router.get("/platform")
async def get_platform(platform_settings: PlatformSettingsDep) -> PublicPlatform:
    """The organisation's public name and support email (Settings, Organisation)."""
    organisation = platform_settings.organisation
    return PublicPlatform(
        platform_name=organisation.platform_name, support_email=organisation.support_email
    )
