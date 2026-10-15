"""Homeowners as customers: a record per email address, signed in by emailed magic links."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Customer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Created automatically from the first quote request; there is no registration form."""

    __tablename__ = "customers"
    __table_args__ = (CheckConstraint("email = lower(email)", name="email_lowercase"),)

    email: Mapped[str] = mapped_column(String(254), unique=True)
    first_name: Mapped[str] = mapped_column(String(60))
    phone: Mapped[str | None] = mapped_column(String(30))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CustomerLoginLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A magic link. Only the SHA-256 of the token is stored; it expires and is used once
    (with a short grace period so an email scanner opening it first does not lock the
    customer out)."""

    __tablename__ = "customer_login_links"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CustomerSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The signed-in browser after a magic link: an opaque token (hashed here) that expires
    after a period of inactivity and, regardless of use, after an absolute lifetime."""

    __tablename__ = "customer_sessions"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
