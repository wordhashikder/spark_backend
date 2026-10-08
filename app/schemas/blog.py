"""Blog post bodies: the public listing and article, and the admin's create/update requests."""

import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints, model_validator

from app.core.enums import BlogPostStatus
from app.core.exceptions import FieldValueError
from app.schemas.common import ImageUrl, blank_as_none, text

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
# `/blog/page/<n>/` is the frontend's pagination path, so no post may be called "page".
RESERVED_SLUGS = frozenset({"page"})
DEFAULT_AUTHOR = "PickASparky Team"

Slug = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=120, pattern=SLUG_PATTERN),
]
Title = Annotated[str, text(3, 160)]
Excerpt = Annotated[str, text(20, 300)]
# Markdown. 100,000 characters is far beyond any article and well inside the 1 MB body limit.
Body = Annotated[str, text(50, 100_000)]
Category = Annotated[str, text(2, 60)]
Author = Annotated[str, text(2, 80)]
AltText = Annotated[Annotated[str, text(1, 160)] | None, blank_as_none]
SeoTitle = Annotated[Annotated[str, text(1, 70)] | None, blank_as_none]
SeoDescription = Annotated[Annotated[str, text(1, 160)] | None, blank_as_none]


def _check_slug(slug: str | None) -> None:
    if slug in RESERVED_SLUGS:
        raise FieldValueError("slug", "This web address is reserved. Choose another.")


class BlogPostSummary(BaseModel):
    """A card in the public listing."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    title: str
    excerpt: str
    category: str
    category_slug: str
    author_name: str
    cover_image_url: str | None
    cover_image_alt: str | None
    reading_minutes: int
    is_featured: bool
    published_at: datetime
    updated_at: datetime


class BlogPostDetail(BlogPostSummary):
    """A published article."""

    body: str
    seo_title: str | None
    seo_description: str | None


class AdminBlogPost(BaseModel):
    """A post as the back office sees it, drafts included."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str
    excerpt: str
    body: str
    category: str
    category_slug: str
    author_name: str
    cover_image_url: str | None
    cover_image_alt: str | None
    seo_title: str | None
    seo_description: str | None
    reading_minutes: int
    is_featured: bool
    status: BlogPostStatus
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BlogPostCreate(BaseModel):
    title: Title
    # Generated from the title when omitted (de-duplicated with a numeric suffix).
    slug: Annotated[Slug | None, blank_as_none] = None
    excerpt: Excerpt
    body: Body
    category: Category
    author_name: Author = DEFAULT_AUTHOR
    cover_image_url: Annotated[ImageUrl | None, blank_as_none] = None
    cover_image_alt: AltText = None
    seo_title: SeoTitle = None
    seo_description: SeoDescription = None
    is_featured: bool = False
    status: BlogPostStatus = BlogPostStatus.DRAFT
    # Publishing without a date publishes now; a future date schedules the post.
    published_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _slug_not_reserved(self) -> Self:
        _check_slug(self.slug)
        return self


# Fields an update may change but never empty.
_REQUIRED_ON_UPDATE = ("title", "slug", "excerpt", "body", "category", "author_name", "status")


class BlogPostUpdate(BaseModel):
    """Partial update: only the fields sent are changed; send `null` to clear an optional one."""

    title: Title | None = None
    slug: Slug | None = None
    excerpt: Excerpt | None = None
    body: Body | None = None
    category: Category | None = None
    author_name: Author | None = None
    cover_image_url: Annotated[ImageUrl | None, blank_as_none] = None
    cover_image_alt: AltText = None
    seo_title: SeoTitle = None
    seo_description: SeoDescription = None
    is_featured: bool | None = None
    status: BlogPostStatus | None = None
    published_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        for name in _REQUIRED_ON_UPDATE:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise FieldValueError(name, "This field is required.")
        if "is_featured" in self.model_fields_set and self.is_featured is None:
            raise FieldValueError("is_featured", "This field is required.")
        _check_slug(self.slug)
        return self
