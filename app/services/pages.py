"""
Website pages built in the Dashboard: a main page with supporting pages, each with its own
address. This module serves the public site (a page by address, its supporting pages, the
sitemap) and the team's editing (create, change, move, delete, preview).

Rules the website relies on:
- A page is reachable once published. Search engines are only asked to index it, and the
  sitemap only lists it, once it also has content (`SitePage.is_indexable`).
- A page moved to a new address keeps answering at the old one with a permanent redirect.
- A supporting page belongs to a main page (itself a page with no main page, or a built-in
  one such as /uk/accreditations/). Two levels only.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.exceptions import ConflictError, FieldValidationError, NotFoundError
from app.models import AccreditationScheme, SitePage
from app.schemas.page import (
    AdminPage,
    PageCard,
    PageCreate,
    PageDetail,
    PageLookup,
    PageRef,
    PageSitemapEntry,
    PageUpdate,
)

ACCREDITATIONS_PATH = "/uk/accreditations/"
# Built-in pages that can be the main page of supporting pages (path -> title).
BUILT_IN_MAIN_PAGES: dict[str, str] = {ACCREDITATIONS_PATH: "Electrician Accreditations"}

# Addresses the website itself uses. A page cannot take them, or it would hide (or be hidden by)
# the real one. Keep in step with `frontend/src/app` and `frontend/public`.
_RESERVED_FIRST_SEGMENTS = frozenset(
    {
        "about",
        "api",
        "blog",
        "contact",
        "cookie-policy",
        "electrical-safety-regulations",
        "electrician-accreditations",
        "electricians-agreement",
        "faq",
        "get-quotes",
        "icons",
        "images",
        "how-it-works",
        "how-we-vet-installers",
        "installer",
        "join",
        "messages",
        "privacy-policy",
        "review",
        "search",  # the old address of /uk/search/, now a redirect
        "terms-and-conditions",
    }
)
_RESERVED_UK_SUBTREES = frozenset({"ev-charger-installers", "installer", "my-quotes", "search"})
_RESERVED_EXACT = frozenset({"/uk/", ACCREDITATIONS_PATH})


def scheme_page_path(key: str) -> str:
    return f"{ACCREDITATIONS_PATH}{key}/"


def check_address(path: str) -> None:
    """Refuse addresses the website already uses."""
    parts = path.strip("/").split("/")
    if (
        path in _RESERVED_EXACT
        or parts[0] in _RESERVED_FIRST_SEGMENTS
        or (parts[0] == "uk" and len(parts) > 1 and parts[1] in _RESERVED_UK_SUBTREES)
    ):
        raise FieldValidationError(
            {"path": "The website already uses this address. Choose another."}
        )


# ---- Public ---------------------------------------------------------------------------


async def _by_path(session: AsyncSession, path: str) -> SitePage | None:
    return await session.scalar(select(SitePage).where(SitePage.path == path))


async def _children(session: AsyncSession, path: str) -> list[SitePage]:
    """Published supporting pages that have something to read, in the order they were made."""
    pages = await session.scalars(
        select(SitePage)
        .where(SitePage.parent_path == path, SitePage.is_published.is_(True))
        .order_by(SitePage.created_at, SitePage.title)
    )
    return [page for page in pages if page.has_content]


async def _parent_ref(session: AsyncSession, parent_path: str | None) -> PageRef | None:
    if parent_path is None:
        return None
    if parent_path in BUILT_IN_MAIN_PAGES:
        return PageRef(path=parent_path, title=BUILT_IN_MAIN_PAGES[parent_path])
    parent = await _by_path(session, parent_path)
    if parent is None or not parent.is_published:
        return None
    return PageRef(path=parent.path, title=parent.title)


async def _detail(session: AsyncSession, page: SitePage, *, preview: bool = False) -> PageDetail:
    return PageDetail(
        path=page.path,
        title=page.title,
        eyebrow=page.eyebrow,
        intro=page.intro,
        hero_image_url=page.hero_image_url,
        hero_image_alt=page.hero_image_alt,
        sections=page.sections,
        faq=page.faq,
        seo_title=page.seo_title,
        seo_description=page.seo_description,
        updated_at=page.updated_at,
        indexable=page.is_indexable and not preview,
        parent=await _parent_ref(session, page.parent_path),
        children=[PageCard.model_validate(child) for child in await _children(session, page.path)],
        preview=preview,
    )


async def lookup(session: AsyncSession, path: str, preview_token: str | None = None) -> PageLookup:
    """The page at an address, or where it moved to. A valid preview token also shows a draft."""
    page = await _by_path(session, path)
    if page is not None and preview_token:
        try:
            allowed = security.decode_page_preview_token(preview_token) == page.id
        except security.TokenError:
            allowed = False
        if allowed:
            return PageLookup(page=await _detail(session, page, preview=True))
    if page is not None and page.is_published:
        return PageLookup(page=await _detail(session, page))
    moved = await session.scalar(
        select(SitePage.path).where(
            SitePage.previous_paths.contains([path]), SitePage.is_published.is_(True)
        )
    )
    if moved is not None and page is None:
        return PageLookup(redirect_to=moved)
    raise NotFoundError("Page not found.")


async def children_of(session: AsyncSession, parent_path: str) -> list[PageCard]:
    return [PageCard.model_validate(page) for page in await _children(session, parent_path)]


async def sitemap(session: AsyncSession) -> list[PageSitemapEntry]:
    pages = await session.scalars(
        select(SitePage).where(SitePage.is_published.is_(True)).order_by(SitePage.path)
    )
    return [
        PageSitemapEntry(path=page.path, updated_at=page.updated_at)
        for page in pages
        if page.has_content
    ]


# ---- Admin ----------------------------------------------------------------------------


async def _get(session: AsyncSession, page_id: uuid.UUID, *, for_update: bool = False) -> SitePage:
    statement = select(SitePage).where(SitePage.id == page_id)
    if for_update:
        statement = statement.with_for_update()
    page = await session.scalar(statement)
    if page is None:
        raise NotFoundError("Page not found.")
    return page


@dataclass(frozen=True, slots=True)
class _Titles:
    by_path: dict[str, str]
    child_counts: dict[str, int]


async def _titles(session: AsyncSession) -> _Titles:
    titles = dict(BUILT_IN_MAIN_PAGES)
    for path, title in (await session.execute(select(SitePage.path, SitePage.title))).all():
        titles[path] = title
    counts = dict(
        (
            await session.execute(
                select(SitePage.parent_path, func.count())
                .where(SitePage.parent_path.is_not(None))
                .group_by(SitePage.parent_path)
            )
        ).all()
    )
    return _Titles(titles, counts)


def _admin(page: SitePage, titles: _Titles) -> AdminPage:
    result = AdminPage.model_validate(page)
    result.parent_title = titles.by_path.get(page.parent_path) if page.parent_path else None
    result.child_count = titles.child_counts.get(page.path, 0)
    return result


async def list_all(session: AsyncSession) -> list[AdminPage]:
    """Main pages first (A-Z), each followed by the pages that support it."""
    pages = list(await session.scalars(select(SitePage)))
    titles = await _titles(session)
    mains = sorted((p for p in pages if p.parent_path is None), key=lambda p: p.title.lower())
    ordered: list[SitePage] = []
    for main in mains:
        ordered.append(main)
        ordered.extend(
            sorted((p for p in pages if p.parent_path == main.path), key=lambda p: p.title.lower())
        )
    placed = {p.id for p in ordered}
    # Supporting pages of built-in main pages (e.g. one per accreditation scheme).
    for built_in in BUILT_IN_MAIN_PAGES:
        ordered.extend(
            sorted((p for p in pages if p.parent_path == built_in), key=lambda p: p.title.lower())
        )
    placed |= {p.id for p in ordered}
    ordered.extend(p for p in pages if p.id not in placed)
    return [_admin(page, titles) for page in ordered]


async def get(session: AsyncSession, page_id: uuid.UUID) -> AdminPage:
    return _admin(await _get(session, page_id), await _titles(session))


async def _check_free(session: AsyncSession, path: str, exclude: uuid.UUID | None) -> None:
    check_address(path)
    statement = select(SitePage.id).where(SitePage.path == path)
    if exclude is not None:
        statement = statement.where(SitePage.id != exclude)
    if await session.scalar(statement):
        raise FieldValidationError({"path": "Another page already uses this address."})


async def _check_parent(
    session: AsyncSession, parent_path: str | None, *, page_id: uuid.UUID | None, own_path: str
) -> None:
    if parent_path is None:
        return
    if parent_path == own_path:
        raise FieldValidationError({"parent_path": "A page cannot be its own main page."})
    if parent_path in BUILT_IN_MAIN_PAGES:
        return
    parent = await _by_path(session, parent_path)
    if parent is None or parent.parent_path is not None:
        raise FieldValidationError(
            {"parent_path": "Choose a main page (one that is not itself a supporting page)."}
        )
    if page_id is not None and await session.scalar(
        select(SitePage.id).where(SitePage.parent_path == own_path).limit(1)
    ):
        raise FieldValidationError(
            {"parent_path": "This page has supporting pages of its own, so it stays a main page."}
        )


async def create(session: AsyncSession, data: PageCreate) -> AdminPage:
    """Add a page (a draft unless published now); it opens with its title only."""
    await _check_free(session, data.path, None)
    await _check_parent(session, data.parent_path, page_id=None, own_path=data.path)
    page = SitePage(
        path=data.path,
        parent_path=data.parent_path,
        title=data.title,
        is_published=data.is_published,
    )
    session.add(page)
    await session.commit()
    return await get(session, page.id)


async def update(session: AsyncSession, page_id: uuid.UUID, data: PageUpdate) -> AdminPage:
    page = await _get(session, page_id, for_update=True)
    changes = data.model_dump(include=data.model_fields_set)
    new_path = changes.pop("path", None)
    own_path = new_path or page.path
    if "parent_path" in changes:
        await _check_parent(session, changes["parent_path"], page_id=page.id, own_path=own_path)
    if new_path and new_path != page.path:
        await _check_free(session, new_path, page.id)
        old_path = page.path
        page.previous_paths = [
            *(path for path in page.previous_paths if path != new_path),
            old_path,
        ]
        page.path = new_path
        # Supporting pages follow their main page to its new address.
        children = await session.scalars(select(SitePage).where(SitePage.parent_path == old_path))
        for child in children:
            child.parent_path = new_path
    for field, value in changes.items():
        setattr(page, field, value)
    if page.hero_image_url and not page.hero_image_alt:
        raise FieldValidationError(
            {"hero_image_alt": "Describe the image for people who cannot see it."}
        )
    await session.commit()
    return await get(session, page.id)


async def delete(session: AsyncSession, page_id: uuid.UUID) -> None:
    page = await _get(session, page_id, for_update=True)
    if page.scheme_key:
        name = await session.scalar(
            select(AccreditationScheme.name).where(AccreditationScheme.key == page.scheme_key)
        )
        raise ConflictError(
            f"This is the page of the {name} accreditation. Remove the accreditation to remove "
            "its page."
        )
    if await session.scalar(select(SitePage.id).where(SitePage.parent_path == page.path).limit(1)):
        raise ConflictError("Move or delete this page's supporting pages first.")
    await session.delete(page)
    await session.commit()


async def preview(session: AsyncSession, page_id: uuid.UUID) -> tuple[str, int]:
    page = await _get(session, page_id)
    return security.create_page_preview_token(page.id)