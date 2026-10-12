"""Editable website content: reading, saving, resetting and restoring page content.

Only pages the admin has saved have a `site_content` row; every other page serves its
original wording from the registry (`app/content/`). Each save, reset and restore adds a
revision, so the Dashboard can show the page's history and restore any version.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import DOCUMENTS, TOKENS, ContentValidationError, Document
from app.core.exceptions import FieldValidationError, NotFoundError
from app.models import SiteContent, SiteContentRevision, User
from app.models.base import utcnow
from app.schemas.content import (
    ContentDocument,
    ContentRevision,
    ContentSummary,
    PublicContent,
)

MAX_REVISIONS_LISTED = 50


def document(key: str) -> Document:
    found = DOCUMENTS.get(key)
    if found is None:
        raise NotFoundError("Page not found.")
    return found


def cache_tags(key: str) -> list[str]:
    """Website cache tags to refresh after `key` changes. Site-wide content is on every page."""
    return ["content"] if key == "site" else [f"content:{key}"]


async def public(session: AsyncSession, key: str) -> PublicContent:
    doc = document(key)
    stored = await session.get(SiteContent, key)
    return PublicContent(
        key=key,
        content=doc.merge(stored.data if stored else None),
        updated_at=stored.updated_at if stored else None,
    )


async def list_documents(session: AsyncSession) -> list[ContentSummary]:
    rows = {
        row.key: row
        for row in await session.scalars(select(SiteContent).where(SiteContent.key.in_(DOCUMENTS)))
    }
    authors = await _names(session, [row.updated_by_id for row in rows.values()])
    counts = await session.execute(
        select(SiteContentRevision.key, func.count()).group_by(SiteContentRevision.key)
    )
    revisions: dict[str, int] = dict(counts.all())
    return [
        ContentSummary(
            key=key,
            label=doc.label,
            group=doc.group,
            description=doc.description,
            path=doc.path,
            customised=key in rows,
            updated_at=rows[key].updated_at if key in rows else None,
            updated_by=authors.get(rows[key].updated_by_id) if key in rows else None,
            revision_count=revisions.get(key, 0),
        )
        for key, doc in DOCUMENTS.items()
    ]


async def get_for_editing(session: AsyncSession, key: str) -> ContentDocument:
    doc = document(key)
    stored = await session.get(SiteContent, key)
    author = (
        (await _names(session, [stored.updated_by_id])).get(stored.updated_by_id)
        if stored
        else None
    )
    return ContentDocument(
        schema_=doc.schema(),
        defaults=doc.defaults(),
        content=doc.merge(stored.data if stored else None),
        customised=stored is not None,
        updated_at=stored.updated_at if stored else None,
        updated_by=author,
        tokens=TOKENS,
    )


async def save(session: AsyncSession, key: str, data: Any, actor: User) -> ContentDocument:
    doc = document(key)
    try:
        cleaned = doc.clean(data)
    except ContentValidationError as exc:
        raise FieldValidationError(exc.fields) from exc
    await _store(session, key, cleaned, actor, "saved")
    await session.commit()
    return await get_for_editing(session, key)


async def reset(session: AsyncSession, key: str, actor: User) -> ContentDocument:
    """Back to the original wording; the edited version stays in the history."""
    document(key)
    stored = await session.get(SiteContent, key)
    if stored is not None:
        await session.delete(stored)
        session.add(SiteContentRevision(key=key, data=None, action="reset", author_id=actor.id))
        await session.commit()
    return await get_for_editing(session, key)


async def revisions(session: AsyncSession, key: str) -> list[ContentRevision]:
    document(key)
    rows = list(
        await session.scalars(
            select(SiteContentRevision)
            .where(SiteContentRevision.key == key)
            .order_by(SiteContentRevision.created_at.desc(), SiteContentRevision.id.desc())
            .limit(MAX_REVISIONS_LISTED)
        )
    )
    authors = await _names(session, [row.author_id for row in rows])
    return [
        ContentRevision(
            id=row.id,
            action=row.action,
            created_at=row.created_at,
            author=authors.get(row.author_id),
        )
        for row in rows
    ]


async def restore(
    session: AsyncSession, key: str, revision_id: uuid.UUID, actor: User
) -> ContentDocument:
    doc = document(key)
    revision = await session.get(SiteContentRevision, revision_id)
    if revision is None or revision.key != key:
        raise NotFoundError("Version not found.")
    if revision.data is None:
        stored = await session.get(SiteContent, key)
        if stored is not None:
            await session.delete(stored)
        session.add(SiteContentRevision(key=key, data=None, action="restored", author_id=actor.id))
    else:
        # Restored content is validated against today's schema; fields added since then
        # take their original wording.
        cleaned = doc.clean(doc.merge(revision.data))
        await _store(session, key, cleaned, actor, "restored")
    await session.commit()
    return await get_for_editing(session, key)


async def _store(
    session: AsyncSession, key: str, data: dict[str, Any], actor: User, action: str
) -> None:
    stored = await session.get(SiteContent, key, with_for_update=True)
    if stored is None:
        session.add(SiteContent(key=key, data=data, updated_by_id=actor.id))
    else:
        stored.data = data
        stored.updated_by_id = actor.id
        stored.updated_at = utcnow()
    session.add(SiteContentRevision(key=key, data=data, action=action, author_id=actor.id))


async def _names(session: AsyncSession, user_ids: list[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    ids = {user_id for user_id in user_ids if user_id is not None}
    if not ids:
        return {}
    rows = await session.execute(
        select(User.id, User.full_name, User.email).where(User.id.in_(ids))
    )
    return {user_id: full_name or email for user_id, full_name, email in rows}
