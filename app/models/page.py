"""
Pages the team builds in the Dashboard (Website content > Pages): a main page with supporting
pages, each with its own address, text, images and search snippet.
"""

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, false, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SitePage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "site_pages"
    __table_args__ = (Index("ix_site_pages_parent_path", "parent_path"),)

    # The full web address with a trailing slash, e.g. /uk/home-ev-charger-installation/cost/.
    path: Mapped[str] = mapped_column(String(200), unique=True)
    # The main page this one supports (its path), or none for a main page. It can also be
    # a built-in page such as /uk/accreditations/.
    parent_path: Mapped[str | None] = mapped_column(String(200))
    # Addresses this page used to have; they redirect to `path` so no link or search result breaks.
    previous_paths: Mapped[list[str]] = mapped_column(
        ARRAY(String(200)), default=list, server_default=text("'{}'")
    )
    title: Mapped[str] = mapped_column(String(120))
    eyebrow: Mapped[str | None] = mapped_column(String(60))
    intro: Mapped[str | None] = mapped_column(Text)
    hero_image_url: Mapped[str | None] = mapped_column(String(500))
    hero_image_alt: Mapped[str | None] = mapped_column(String(160))
    # [{"heading", "body" (Markdown, may contain images), "image_url", "image_alt",
    #   "cards": [{"icon", "title", "description"}]}]
    sections: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # [{"question", "answer"}]
    faq: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    seo_title: Mapped[str | None] = mapped_column(String(70))
    seo_description: Mapped[str | None] = mapped_column(String(160))
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Set for the page that belongs to an accreditation scheme (deleted with it).
    scheme_key: Mapped[str | None] = mapped_column(
        String(40),
        ForeignKey("accreditation_schemes.key", ondelete="CASCADE"),
        unique=True,
    )

    @property
    def has_content(self) -> bool:
        """A page with no sections and no questions is an empty shell: reachable but not indexed."""
        return bool(self.sections) or bool(self.faq)

    @property
    def is_indexable(self) -> bool:
        return self.is_published and self.has_content
