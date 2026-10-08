"""The public blog: listing, articles and related posts (published posts only)."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import PageDep, SessionDep
from app.schemas.blog import BlogPostDetail, BlogPostSummary
from app.schemas.common import Paginated
from app.services import blog

router = APIRouter(prefix="/blog", tags=["blog"])

_DEFAULT_RELATED = 3


@router.get("/posts")
async def list_posts(
    session: SessionDep,
    page: PageDep,
    category: Annotated[str | None, Query(max_length=80)] = None,
) -> Paginated[BlogPostSummary]:
    found, total = await blog.list_published(
        session, category_slug=category, offset=page.offset, limit=page.page_size
    )
    return Paginated.build(
        [BlogPostSummary.model_validate(post) for post in found],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/posts/{slug}")
async def get_post(slug: str, session: SessionDep) -> BlogPostDetail:
    return BlogPostDetail.model_validate(await blog.get_published(session, slug))


@router.get("/posts/{slug}/related")
async def list_related_posts(
    slug: str,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=blog.MAX_RELATED)] = _DEFAULT_RELATED,
) -> list[BlogPostSummary]:
    related = await blog.list_related(session, slug, limit)
    return [BlogPostSummary.model_validate(post) for post in related]
