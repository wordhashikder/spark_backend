"""Messages sent through the public contact form."""

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ContactSubject
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum


class ContactMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "contact_messages"
    __table_args__ = (Index("ix_contact_messages_created_at", "created_at"),)

    name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(254))
    subject: Mapped[ContactSubject] = mapped_column(pg_enum(ContactSubject, "contact_subject"))
    message: Mapped[str] = mapped_column(Text)
