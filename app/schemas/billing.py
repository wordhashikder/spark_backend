"""Billing request and response bodies."""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel

from app.core.enums import SubscriptionStatus
from app.models import BillingActivity, BillingInvoice
from app.schemas.plan import PlanKey

PlanAction = Literal["current", "subscribe", "upgrade", "downgrade", "cancel"]
CheckoutState = Literal["paid", "processing", "open", "expired"]


# Where Stripe sends the person afterwards: the Dashboard's Plan & billing page (default), or
# the website's account page (used by the "Upgrade" buttons there).
ReturnTo = Literal["dashboard", "website"]


class CheckoutRequest(BaseModel):
    plan: PlanKey
    return_to: ReturnTo = "dashboard"


class PortalRequest(BaseModel):
    return_to: ReturnTo = "dashboard"


class ChangePlanRequest(BaseModel):
    plan: PlanKey


class SessionUrl(BaseModel):
    url: str


class PlanOption(BaseModel):
    """A plan the installer can move to, and what moving there means for them."""

    key: str
    name: str
    tagline: str | None
    features: list[str]
    is_popular: bool
    price_pence: int | None
    currency: str
    action: PlanAction


class PlanRef(BaseModel):
    key: str
    name: str


class PendingChange(BaseModel):
    plan: PlanRef
    effective_at: datetime | None


class BillingSummary(BaseModel):
    # False while Stripe is not set up: plans can be viewed but not bought or changed.
    billing_enabled: bool
    plan: PlanRef
    subscription_status: SubscriptionStatus
    has_billing_account: bool
    has_subscription: bool
    # The paid plan keeps renewing: a subscription that is not set to end.
    auto_renew: bool
    cancel_at_period_end: bool
    current_period_end: datetime | None
    # What the installer pays each month (their own price, which may be an older one).
    price_pence: int | None
    currency: str
    pending_change: PendingChange | None
    payment_failed: bool
    options: list[PlanOption]


class CheckoutStatus(BaseModel):
    state: CheckoutState
    plan: PlanRef | None = None


class InvoiceOut(BaseModel):
    id: str
    number: str | None
    status: str
    description: str | None
    plan_name: str | None
    amount_due_pence: int
    amount_paid_pence: int
    currency: str
    billing_reason: str | None
    hosted_invoice_url: str | None
    invoice_pdf_url: str | None
    period_start: datetime | None
    period_end: datetime | None
    issued_at: datetime
    paid_at: datetime | None

    @classmethod
    def from_invoice(cls, invoice: BillingInvoice) -> Self:
        return cls(
            id=invoice.id,
            number=invoice.number,
            status=invoice.status,
            description=invoice.description,
            plan_name=invoice.plan_name,
            amount_due_pence=invoice.amount_due_pence,
            amount_paid_pence=invoice.amount_paid_pence,
            currency=invoice.currency,
            billing_reason=invoice.billing_reason,
            hosted_invoice_url=invoice.hosted_invoice_url,
            invoice_pdf_url=invoice.invoice_pdf_url,
            period_start=invoice.period_start,
            period_end=invoice.period_end,
            issued_at=invoice.issued_at,
            paid_at=invoice.paid_at,
        )


class AdminInvoice(InvoiceOut):
    installer_id: str
    business_name: str


class ActivityOut(BaseModel):
    kind: str
    message: str
    from_plan: str | None
    to_plan: str | None
    created_at: datetime

    @classmethod
    def from_activity(cls, activity: BillingActivity) -> Self:
        return cls(
            kind=activity.kind,
            message=activity.message,
            from_plan=activity.from_plan,
            to_plan=activity.to_plan,
            created_at=activity.created_at,
        )


class PaymentsOverview(BaseModel):
    """Headline subscription numbers for the team's Plans & billing page."""

    active_subscriptions: int
    monthly_recurring_pence: int
    past_due: int
    cancelling: int
    paid_last_30_days_pence: int
    currency: str = "gbp"


class StripeSyncResult(BaseModel):
    plans_updated: int
