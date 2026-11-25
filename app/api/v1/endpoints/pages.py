"""
Website pages built in the Dashboard, and the accreditation schemes: what the public site reads.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import SessionDep
from app.schemas.accreditation import AccreditationSchemePublic
from app.schemas.page import PageCard, PageLookup, PageSitemapEntry
from app.services import accreditation_schemes, pages

router = APIRouter(tags=["pages"])

PathQuery = Annotated[str, Query(min_length=1, max_length=200, pattern=r"^/[a-z0-9/-]*$")]


@router.get("/pages/lookup")
async def lookup_page(
    session: SessionDep,
    path: PathQuery,
    preview: Annotated[str | None, Query(max_length=2048)] = None,
) -> PageLookup:
    """The page at an address (or where it moved to). `preview` is the team's preview token."""
    return await pages.lookup(session, path, preview)


@router.get("/pages/children")
async def list_supporting_pages(session: SessionDep, parent: PathQuery) -> list[PageCard]:
    """Published supporting pages that have content, for a main page (built-in ones included)."""
    return await pages.children_of(session, parent)


@router.get("/pages/sitemap")
async def page_sitemap(session: SessionDep) -> list[PageSitemapEntry]:
    return await pages.sitemap(session)


@router.get("/accreditation-schemes")
async def list_accreditation_schemes(session: SessionDep) -> list[AccreditationSchemePublic]:
    return await accreditation_schemes.list_public(session)
