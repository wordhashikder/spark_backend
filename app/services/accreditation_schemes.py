"""
Accreditation schemes (NICEIC, NAPIT, ...): what installers can list, how the profile card
describes them, and the page each scheme has under /uk/accreditations/.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, FieldValidationError, NotFoundError
from app.models import AccreditationScheme, InstallerAccreditation, SitePage
from app.schemas.accreditation import (
    AccreditationSchemeCreate,
    AccreditationSchemePublic,
    AccreditationSchemeUpdate,
    AdminAccreditationScheme,
)
from app.services.installers import slugify
from app.services.pages import ACCREDITATIONS_PATH, scheme_page_path

_KEY_MAX = 40
_STEP = 10


async def _pages_by_scheme(session: AsyncSession) -> dict[str, SitePage]:
    pages = await session.scalars(select(SitePage).where(SitePage.scheme_key.is_not(None)))
    return {page.scheme_key: page for page in pages if page.scheme_key}


def _public(scheme: AccreditationScheme, page: SitePage | None) -> AccreditationSchemePublic:
    result = AccreditationSchemePublic.model_validate(scheme)
    # The link only appears once the page is published and has something to read.
    result.href = page.path if page is not None and page.is_indexable else None
    return result


async def list_public(session: AsyncSession) -> list[AccreditationSchemePublic]:
    """Every scheme, in order. Profiles show a scheme an installer already holds even if the
    team has since switched it off; installers' pickers offer only the active ones."""
    pages = await _pages_by_scheme(session)
    schemes = await session.scalars(
        select(AccreditationScheme).order_by(AccreditationScheme.position, AccreditationScheme.name)
    )
    return [_public(scheme, pages.get(scheme.key)) for scheme in schemes]


async def list_admin(session: AsyncSession) -> list[AdminAccreditationScheme]:
    pages = await _pages_by_scheme(session)
    counts = dict(
        (
            await session.execute(
                select(InstallerAccreditation.scheme, func.count()).group_by(
                    InstallerAccreditation.scheme
                )
            )
        ).all()
    )
    schemes = await session.scalars(
        select(AccreditationScheme).order_by(AccreditationScheme.position, AccreditationScheme.name)
    )
    result = []
    for scheme in schemes:
        page = pages.get(scheme.key)
        result.append(
            AdminAccreditationScheme(
                **_public(scheme, page).model_dump(),
                position=scheme.position,
                installer_count=counts.get(scheme.key, 0),
                page_id=page.id if page else None,
                page_path=page.path if page else None,
                page_published=bool(page and page.is_published),
                page_has_content=bool(page and page.has_content),
            )
        )
    return result


async def _get(session: AsyncSession, key: str) -> AccreditationScheme:
    scheme = await session.get(AccreditationScheme, key, with_for_update=True)
    if scheme is None:
        raise NotFoundError("Accreditation not found.")
    return scheme


async def _unique_key(session: AsyncSession, name: str) -> str:
    base = slugify(name, fallback="scheme")[:_KEY_MAX].strip("-")
    taken = set(
        await session.scalars(
            select(AccreditationScheme.key).where(AccreditationScheme.key.like(f"{base}%"))
        )
    )
    taken_paths = set(
        await session.scalars(
            select(SitePage.path).where(SitePage.path.like(f"{ACCREDITATIONS_PATH}%"))
        )
    )
    key, suffix = base, 2
    while key in taken or scheme_page_path(key) in taken_paths:
        tail = f"-{suffix}"
        key = f"{base[: _KEY_MAX - len(tail)].strip('-')}{tail}"
        suffix += 1
    return key


async def create(session: AsyncSession, data: AccreditationSchemeCreate) -> AccreditationScheme:
    """Add a scheme and its (empty, not yet indexed) page /uk/accreditations/<key>/."""
    if await session.scalar(
        select(AccreditationScheme.key).where(
            func.lower(AccreditationScheme.name) == data.name.lower()
        )
    ):
        raise FieldValidationError({"name": "This accreditation is already in the list."})
    key = await _unique_key(session, data.name)
    position = data.position
    if position is None:
        top = await session.scalar(select(func.max(AccreditationScheme.position)))
        position = (top or 0) + _STEP
    scheme = AccreditationScheme(
        key=key,
        name=data.name,
        badge=data.badge,
        card_title=data.card_title,
        card_text=data.card_text,
        position=position,
    )
    session.add(scheme)
    await session.flush()
    session.add(
        SitePage(
            path=scheme_page_path(key),
            parent_path=ACCREDITATIONS_PATH,
            title=data.name,
            is_published=True,
            scheme_key=key,
        )
    )
    await session.commit()
    return scheme


async def update(
    session: AsyncSession, key: str, data: AccreditationSchemeUpdate
) -> AccreditationScheme:
    scheme = await _get(session, key)
    changes = data.model_dump(include=data.model_fields_set)
    new_name = changes.get("name")
    if (
        new_name
        and new_name.lower() != scheme.name.lower()
        and await session.scalar(
            select(AccreditationScheme.key).where(
                func.lower(AccreditationScheme.name) == new_name.lower(),
                AccreditationScheme.key != key,
            )
        )
    ):
        raise FieldValidationError({"name": "This accreditation is already in the list."})
    for field, value in changes.items():
        setattr(scheme, field, value)
    await session.commit()
    return scheme


async def delete(session: AsyncSession, key: str) -> None:
    """Remove a scheme nobody lists (its page goes with it); otherwise switch it off instead."""
    scheme = await _get(session, key)
    in_use = await session.scalar(
        select(func.count())
        .select_from(InstallerAccreditation)
        .where(InstallerAccreditation.scheme == key)
    )
    if in_use:
        raise ConflictError(
            f"{in_use} installer(s) list {scheme.name}. Switch it off instead; "
            "they keep it on their profile."
        )
    await session.delete(scheme)
    await session.commit()


async def name_lookup(session: AsyncSession) -> dict[str, str]:
    """`niceic` and `NICEIC` (lower-cased key or name) -> key, for CSV imports."""
    lookup: dict[str, str] = {}
    for scheme in await session.scalars(
        select(AccreditationScheme).where(AccreditationScheme.is_active.is_(True))
    ):
        lookup[scheme.key.lower()] = scheme.key
        lookup[scheme.name.lower()] = scheme.key
    return lookup


async def require_offered(
    session: AsyncSession, keys: list[str], *, already_held: frozenset[str] = frozenset()
) -> None:
    """Every key must be a known scheme that is on (or one the installer already holds)."""
    if not keys:
        return
    rows = (
        await session.execute(
            select(AccreditationScheme.key, AccreditationScheme.is_active).where(
                AccreditationScheme.key.in_(keys)
            )
        )
    ).all()
    allowed = {key for key, active in rows if active or key in already_held}
    unknown = [key for key in dict.fromkeys(keys) if key not in allowed]
    if unknown:
        raise FieldValidationError(
            {"accreditations": f"Unknown accreditation: {', '.join(unknown)}."}
        )


__all__ = [
    "create",
    "delete",
    "list_admin",
    "list_public",
    "name_lookup",
    "require_offered",
    "update",
]