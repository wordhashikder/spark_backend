"""In-app conversations between an installer and a homeowner: messages and priced quotes.

A conversation belongs to one job: either a lead (a quote request matched to the installer)
or a direct enquiry sent from the installer's profile. Every message and quote is kept as
the history of the job; emails tell the other side something new has arrived.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import MessageSender, OfferStatus
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.enquiry import InstallerEnquiry
from app.models.installer import Installer
from app.models.quote import QuoteMatch


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint("(quote_match_id IS NULL) <> (enquiry_id IS NULL)", name="exactly_one_job"),
        Index("ix_conversations_installer_id_last_message_at", "installer_id", "last_message_at"),
    )

    installer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("installers.id", ondelete="CASCADE"))
    quote_match_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("quote_matches.id", ondelete="CASCADE"), unique=True
    )
    enquiry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("installer_enquiries.id", ondelete="CASCADE"), unique=True
    )
    # Copied from the request, so a homeowner account can later find its conversations.
    homeowner_name: Mapped[str] = mapped_column(String(80))
    homeowner_email: Mapped[str] = mapped_column(String(254), index=True)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    installer_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    homeowner_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    installer: Mapped[Installer] = relationship(lazy="raise")
    quote_match: Mapped[QuoteMatch | None] = relationship(lazy="raise")
    enquiry: Mapped[InstallerEnquiry | None] = relationship(lazy="raise")
    messages: Mapped[list[ConversationMessage]] = relationship(
        back_populates="conversation",
        order_by="ConversationMessage.created_at",
        passive_deletes=True,
        lazy="raise",
    )
    offers: Mapped[list[Offer]] = relationship(
        back_populates="conversation",
        order_by="Offer.created_at",
        passive_deletes=True,
        lazy="raise",
    )


class ConversationMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index(
            "ix_conversation_messages_conversation_id_created_at",
            "conversation_id",
            "created_at",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    sender: Mapped[MessageSender] = mapped_column(pg_enum(MessageSender, "message_sender"))
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    body: Mapped[str] = mapped_column(Text)

    conversation: Mapped[Conversation] = relationship(back_populates="messages", lazy="raise")


class Offer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A priced quote from the installer. Shown to people as a "quote"."""

    __tablename__ = "offers"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_offers_installer_id_created_at", "installer_id", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    installer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("installers.id", ondelete="CASCADE"))
    reference: Mapped[str] = mapped_column(String(12), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    includes_vat: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    description: Mapped[str] = mapped_column(Text)
    valid_until: Mapped[date | None] = mapped_column(Date)
    status: Mapped[OfferStatus] = mapped_column(
        pg_enum(OfferStatus, "offer_status"),
        default=OfferStatus.SENT,
        server_default=OfferStatus.SENT.value,
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_note: Mapped[str | None] = mapped_column(Text)

    conversation: Mapped[Conversation] = relationship(back_populates="offers", lazy="raise")
