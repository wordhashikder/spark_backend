"""Documents the back office edits: platform settings, page content and the role matrix."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import StaffRole
from app.models.base import Base, pg_enum, utcnow


class _EditedDocument:
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class PlatformSetting(_EditedDocument, Base):
    """Platform-wide settings (matching rules, notifications, organisation), one row per key."""

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)


class SiteContent(_EditedDocument, Base):
    """The admin's version of one public page's editable content (see `app/content/`).

    Only pages the admin has saved have a row; the others use the built-in defaults.
    """

    __tablename__ = "site_content"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)


class SiteContentRevision(Base):
    """Every saved version of a page's content, newest last: the page's edit history.

    Written on each save, reset and restore, so any earlier version can be restored and
    the Dashboard can show who changed what and when.
    """

    __tablename__ = "site_content_revisions"
    __table_args__ = (Index("ix_site_content_revisions_key_created_at", "key", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid7)
    key: Mapped[str] = mapped_column(String(60))
    # The page's content after the change; null when it was reset to the original wording.
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    action: Mapped[str] = mapped_column(String(20))  # saved | reset | restored
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class RolePermission(Base):
    """One cell of the role matrix: may `staff_role` use `module`? Missing cells use defaults."""

    __tablename__ = "role_permissions"

    staff_role: Mapped[StaffRole] = mapped_column(
        pg_enum(StaffRole, "staff_role"), primary_key=True
    )
    module: Mapped[str] = mapped_column(String(40), primary_key=True)
    allowed: Mapped[bool] = mapped_column(Boolean)
