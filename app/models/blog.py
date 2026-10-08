"""Blog posts written and published by the admin."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import BlogPostStatus
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum


class BlogPost(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "blog_posts"
    __table_args__ = (
        # The public listing: published posts, newest first.
        Index("ix_blog_posts_status_published_at", "status", "published_at"),
    )

    slug: Mapped[str] = mapped_column(String(120), unique=True)
    title: Mapped[str] = mapped_column(String(160))
    excerpt: Mapped[str] = mapped_column(String(300))
    # Markdown. Rendered by the frontend without raw HTML, so it cannot inject markup.
    body: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(60))
    category_slug: Mapped[str] = mapped_column(String(80), index=True)
    author_name: Mapped[str] = mapped_column(String(80))
    cover_image_url: Mapped[str | None] = mapped_column(String(500))
    cover_image_alt: Mapped[str | None] = mapped_column(String(160))
    # Set only for covers uploaded to Cloudinary, so a replaced cover can be deleted there.
    cover_image_public_id: Mapped[str | None] = mapped_column(String(255))
    seo_title: Mapped[str | None] = mapped_column(String(70))
    seo_description: Mapped[str | None] = mapped_column(String(160))
    reading_minutes: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    status: Mapped[BlogPostStatus] = mapped_column(
        pg_enum(BlogPostStatus, "blog_post_status"),
        default=BlogPostStatus.DRAFT,
        server_default=BlogPostStatus.DRAFT.value,
    )
    # Visible to the public once `status` is published and this moment has passed,
    # so a post can be scheduled by publishing it with a future date.
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
