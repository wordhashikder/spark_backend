"""Stripe bookkeeping: handled webhook events, invoices (payment history) and plan activity."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class StripeEvent(TimestampMixin, Base):
    """Every Stripe event already handled, keyed by Stripe's event id (webhook idempotency)."""

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    type: Mapped[str] = mapped_column(String(120))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BillingInvoice(TimestampMixin, Base):
    """A Stripe invoice, kept so payment history loads without calling Stripe.

    Keyed by Stripe's invoice id, so webhook redeliveries and the checkout confirmation
    update the same row.
    """

    __tablename__ = "billing_invoices"
    __table_args__ = (Index("ix_billing_invoices_installer_issued", "installer_id", "issued_at"),)

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    installer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("installers.id", ondelete="CASCADE"))
    number: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(String(300))
    # The plan's name when the invoice was raised (a later rename must not rewrite history).
    plan_name: Mapped[str | None] = mapped_column(String(60))
    amount_due_pence: Mapped[int] = mapped_column(Integer, default=0)
    amount_paid_pence: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="gbp")
    billing_reason: Mapped[str | None] = mapped_column(String(40))
    hosted_invoice_url: Mapped[str | None] = mapped_column(Text)
    invoice_pdf_url: Mapped[str | None] = mapped_column(Text)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BillingActivity(UUIDPrimaryKeyMixin, Base):
    """A plain-language trail of subscription changes for an installer."""

    __tablename__ = "billing_activity"
    __table_args__ = (Index("ix_billing_activity_installer_created", "installer_id", "created_at"),)

    installer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("installers.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(300))
    from_plan: Mapped[str | None] = mapped_column(String(40))
    to_plan: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
