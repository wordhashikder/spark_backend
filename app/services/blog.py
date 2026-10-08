"""The blog: public listing and articles, and the admin's writing, publishing and covers."""

import math
import re
import uuid
from typing import Any

from sqlalchemy import ColumnElement, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import BlogPostStatus
from app.core.exceptions import ConflictError, NotFoundError
from app.models import BlogPost
from app.models.base import utcnow
from app.schemas.blog import BlogPostCreate, BlogPostUpdate
from app.services.installers import slugify
from app.services.storage import ImageStorage, discard_quietly, validate_image

MAX_RELATED = 6
_WORDS_PER_MINUTE = 200
_WORD = re.compile(r"\w+")


class SlugTakenError(ConflictError):
    code = "slug_taken"
    message = "Another post already uses this web address."

    def __init__(self) -> None:
        super().__init__(fields={"slug": "Another post already uses this web address."})


def reading_minutes(markdown: str) -> int:
    return max(1, math.ceil(len(_WORD.findall(markdown)) / _WORDS_PER_MINUTE))


def _is_live() -> ColumnElement[bool]:
    """SQL filter: published, and the publication time has arrived (not scheduled)."""
    return and_(
        BlogPost.status == BlogPostStatus.PUBLISHED,
        BlogPost.published_at.is_not(None),
        BlogPost.published_at <= func.now(),
    )


# ---- Public ---------------------------------------------------------------------------


async def list_published(
    session: AsyncSession, *, category_slug: str | None, offset: int, limit: int
) -> tuple[list[BlogPost], int]:
    """Live posts, newest first, optionally from one category."""
    filters = [_is_live()]
    if category_slug:
        filters.append(BlogPost.category_slug == category_slug)
    total = await session.scalar(select(func.count()).select_from(BlogPost).where(*filters))
    posts = await session.scalars(
        select(BlogPost)
        .where(*filters)
        .order_by(BlogPost.published_at.desc(), BlogPost.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(posts), total or 0


async def get_published(session: AsyncSession, slug: str) -> BlogPost:
    post = await session.scalar(select(BlogPost).where(BlogPost.slug == slug, _is_live()))
    if post is None:
        raise NotFoundError("Post not found.")
    return post


async def list_related(session: AsyncSession, slug: str, limit: int) -> list[BlogPost]:
    """Other live posts: the same category first, then the newest."""
    post = await get_published(session, slug)
    same_category = case((BlogPost.category_slug == post.category_slug, 1), else_=0)
    related = await session.scalars(
        select(BlogPost)
        .where(_is_live(), BlogPost.id != post.id)
        .order_by(same_category.desc(), BlogPost.published_at.desc(), BlogPost.id.desc())
        .limit(limit)
    )
    return list(related)


# ---- Admin ----------------------------------------------------------------------------


async def list_all(
    session: AsyncSession, *, status: BlogPostStatus | None, offset: int, limit: int
) -> tuple[list[BlogPost], int]:
    """Every post including drafts, most recently edited first."""
    filters = [BlogPost.status == status] if status else []
    total = await session.scalar(select(func.count()).select_from(BlogPost).where(*filters))
    posts = await session.scalars(
        select(BlogPost)
        .where(*filters)
        .order_by(BlogPost.updated_at.desc(), BlogPost.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(posts), total or 0


async def get(session: AsyncSession, post_id: uuid.UUID, *, for_update: bool = False) -> BlogPost:
    statement = select(BlogPost).where(BlogPost.id == post_id)
    if for_update:
        statement = statement.with_for_update()
    post = await session.scalar(statement)
    if post is None:
        raise NotFoundError("Post not found.")
    return post


async def _slug_is_taken(session: AsyncSession, slug: str, exclude: uuid.UUID | None) -> bool:
    statement = select(BlogPost.id).where(BlogPost.slug == slug)
    if exclude is not None:
        statement = statement.where(BlogPost.id != exclude)
    return await session.scalar(statement) is not None


async def _unique_slug(session: AsyncSession, title: str) -> str:
    """Slug for a title, de-duplicated with a numeric suffix (`title`, `title-2`, ...)."""
    base = slugify(title, fallback="post")
    taken = set(
        await session.scalars(
            select(BlogPost.slug).where(or_(BlogPost.slug == base, BlogPost.slug.like(f"{base}-%")))
        )
    )
    taken.add("page")
    if base not in taken:
        return base
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"


def _date_if_published(post: BlogPost) -> None:
    """Publishing without a date publishes now (a date already set, past or future, is kept)."""
    if post.status is BlogPostStatus.PUBLISHED and post.published_at is None:
        post.published_at = utcnow()


async def create(session: AsyncSession, data: BlogPostCreate) -> BlogPost:
    if data.slug is not None and await _slug_is_taken(session, data.slug, None):
        raise SlugTakenError
    fields: dict[str, Any] = data.model_dump(exclude={"slug"})
    post = BlogPost(
        **fields,
        slug=data.slug or await _unique_slug(session, data.title),
        category_slug=slugify(data.category, fallback="general"),
        reading_minutes=reading_minutes(data.body),
    )
    _date_if_published(post)
    session.add(post)
    await session.commit()
    return post


async def update(
    session: AsyncSession, post_id: uuid.UUID, data: BlogPostUpdate, storage: ImageStorage
) -> BlogPost:
    """Change the fields that were sent. A new or cleared cover URL releases an uploaded cover."""
    post = await get(session, post_id, for_update=True)
    changes = data.model_dump(include=data.model_fields_set)
    if "slug" in changes and await _slug_is_taken(session, changes["slug"], post.id):
        raise SlugTakenError

    replaced_public_id = None
    if "cover_image_url" in changes and changes["cover_image_url"] != post.cover_image_url:
        replaced_public_id = post.cover_image_public_id
        post.cover_image_public_id = None
    for field, value in changes.items():
        setattr(post, field, value)
    if "category" in changes:
        post.category_slug = slugify(post.category, fallback="general")
    if "body" in changes:
        post.reading_minutes = reading_minutes(post.body)
    _date_if_published(post)

    await session.commit()
    await discard_quietly(storage, replaced_public_id)
    return post


async def delete(session: AsyncSession, post_id: uuid.UUID, storage: ImageStorage) -> None:
    post = await get(session, post_id, for_update=True)
    public_id = post.cover_image_public_id
    await session.delete(post)
    await session.commit()
    await discard_quietly(storage, public_id)


async def set_cover(
    session: AsyncSession,
    post_id: uuid.UUID,
    data: bytes,
    alt: str | None,
    storage: ImageStorage,
) -> BlogPost:
    post = await get(session, post_id, for_update=True)
    validate_image(data)
    stored = await storage.upload(data, folder="blog")
    previous_public_id = post.cover_image_public_id
    post.cover_image_url = stored.url
    post.cover_image_public_id = stored.public_id
    post.cover_image_alt = alt or post.title
    await session.commit()
    await discard_quietly(storage, previous_public_id)
    return post


async def remove_cover(
    session: AsyncSession, post_id: uuid.UUID, storage: ImageStorage
) -> BlogPost:
    post = await get(session, post_id, for_update=True)
    previous_public_id = post.cover_image_public_id
    post.cover_image_url = None
    post.cover_image_alt = None
    post.cover_image_public_id = None
    await session.commit()
    await discard_quietly(storage, previous_public_id)
    return post
