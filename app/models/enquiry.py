"""Enquiries sent from the "Request a Quote" form on an installer's profile."""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.installer import Installer


class InstallerEnquiry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "installer_enquiries"
    __table_args__ = (
        Index("ix_installer_enquiries_installer_id_created_at", "installer_id", "created_at"),
        Index("ix_installer_enquiries_created_at", "created_at"),
    )

    installer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("installers.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text)
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)
    # True when the installer was emailed the request (Pro and Premium plans). Requests to
    # Free-plan (listed-only) installers go to the PickASparky team instead.
    sent_to_installer: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    installer: Mapped[Installer] = relationship(lazy="raise")
