"""Subscriptions: checkout, plan changes, cancellation, payment history and Stripe webhooks.

Plans and prices come from the database (`services/plans.py`); nothing here reads a price
from configuration. Stripe is the source of truth for a subscription's state: every change
(made here, in the Stripe billing portal, or by a renewal) ends in `_apply_subscription`,
which mirrors the subscription onto the installer. The webhook and the return from checkout
both go through it, and both are safe to run more than once.

What a change means for the installer:

* Upgrade (to a higher-ranked plan): immediate. The unused time on the old plan is credited,
  the new plan is billed for the rest of the period right away, and the new plan's benefits
  apply at once. If the card is declined nothing changes.
* Downgrade (to a lower-ranked plan): booked for the end of the current period with a
  Stripe subscription schedule. They keep what they paid for until then.
* Cancel: switches auto-renewal off. The plan runs until the period ends, then the account
  returns to the default (free) plan. It can be resumed until then.
* A failed renewal payment withdraws the paid plan straight away; paying restores it.
"""

import json
import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import stripe
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import SubscriptionStatus
from app.core.exceptions import (
    AppError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    ServiceNotConfiguredError,
)
from app.core.plans import PlanEntry, registry
from app.models import (
    BillingActivity,
    BillingInvoice,
    Installer,
    Plan,
    PlanPrice,
    StripeEvent,
    User,
)
from app.models.base import utcnow
from app.schemas.billing import (
    BillingSummary,
    CheckoutStatus,
    PaymentsOverview,
    PendingChange,
    PlanOption,
    PlanRef,
)
from app.services import email as emails
from app.services import plans as plan_service
from app.services.stripe_gateway import (
    BillingGateway,
    BillingUnavailableError,
    call_stripe,
)

logger = logging.getLogger(__name__)

_WEBHOOK_TOLERANCE_SECONDS = 300
_CHECKOUT_PLACEHOLDER = "{CHECKOUT_SESSION_ID}"
_SUBSCRIPTION_EVENTS = frozenset(
    {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }
)
_SCHEDULE_EVENTS = frozenset(
    {
        "subscription_schedule.created",
        "subscription_schedule.updated",
        "subscription_schedule.released",
        "subscription_schedule.completed",
        "subscription_schedule.canceled",
        "subscription_schedule.aborted",
    }
)
_INVOICE_EVENTS = frozenset({"invoice.paid", "invoice.payment_failed"})
# Stripe subscription statuses folded into ours; anything that is not paid-up maps away
# from ACTIVE, which is the only status that grants a paid plan.
_STATUS_MAP = {
    "active": SubscriptionStatus.ACTIVE,
    "trialing": SubscriptionStatus.ACTIVE,
    "incomplete": SubscriptionStatus.INCOMPLETE,
    "past_due": SubscriptionStatus.PAST_DUE,
    "unpaid": SubscriptionStatus.PAST_DUE,
    "paused": SubscriptionStatus.PAST_DUE,
    "incomplete_expired": SubscriptionStatus.CANCELED,
    "canceled": SubscriptionStatus.CANCELED,
}
_LIVE_SUBSCRIPTION_STATUSES = frozenset({SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE})
# A redelivered or late event must never move an invoice backwards.
_INVOICE_STATUS_RANK = {"draft": 0, "open": 1, "uncollectible": 2, "void": 3, "paid": 3}
_BILLING_COLUMNS = (
    "plan",
    "subscription_status",
    "stripe_customer_id",
    "stripe_subscription_id",
    "current_period_end",
    "cancel_at_period_end",
    "pending_plan",
    "stripe_schedule_id",
    "plan_price_id",
)


# ---- Errors -----------------------------------------------------------------------------


class AlreadySubscribedError(ConflictError):
    code = "already_subscribed"
    message = "You already have a subscription. Use Change plan to switch."


class NoSubscriptionError(ConflictError):
    code = "no_subscription"
    message = "There is no active subscription to change."


class NoBillingAccountError(ConflictError):
    code = "no_billing_account"
    message = "There is no billing account for this installer yet."


class SamePlanError(ConflictError):
    code = "same_plan"
    message = "You are already on this plan."


class PaymentOverdueError(ConflictError):
    code = "payment_overdue"
    message = "Your last payment failed. Update your payment method first."


class NothingToChangeError(ConflictError):
    code = "nothing_to_change"
    message = "There is nothing to change."


class PaymentDeclinedError(AppError):
    status_code = 402
    code = "payment_declined"
    message = (
        "Your card was declined, so nothing was changed. Update your payment method and try again."
    )


class InvalidWebhookError(BadRequestError):
    code = "invalid_webhook"
    message = "The webhook could not be verified."


# ---- Small helpers ----------------------------------------------------------------------


def _require_configured() -> None:
    if not get_settings().stripe_configured:
        raise ServiceNotConfiguredError


def _dashboard_url(path: str) -> str:
    return f"{get_settings().dashboard_url.rstrip('/')}{path}"


def _return_urls(return_to: str) -> tuple[str, str, str]:
    """(checkout success, checkout cancelled, billing page) for where the person came from."""
    if return_to == "website":
        account = f"{get_settings().frontend_url.rstrip('/')}/installer/account"
        return (
            f"{account}?checkout=success&session_id={_CHECKOUT_PLACEHOLDER}",
            f"{account}?checkout=cancelled",
            account,
        )
    return (
        _dashboard_url(f"/billing/success?session_id={_CHECKOUT_PLACEHOLDER}"),
        _dashboard_url("/billing/cancelled"),
        _dashboard_url("/billing"),
    )


def _timestamp(value: Any) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if isinstance(value, int | float) and value else None


def _parse_uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


def _plan_name(key: str | None) -> str:
    entry = registry.get(key)
    return entry.name if entry else (key or "")


def _is_live(installer: Installer) -> bool:
    return (
        installer.stripe_subscription_id is not None
        and installer.subscription_status in _LIVE_SUBSCRIPTION_STATUSES
    )


async def _lock(session: AsyncSession, installer: Installer) -> None:
    """Serialise billing changes for one installer (webhook vs. their own click)."""
    await session.execute(
        select(Installer.id).where(Installer.id == installer.id).with_for_update()
    )
    await session.refresh(installer, attribute_names=list(_BILLING_COLUMNS))


def _log(
    session: AsyncSession,
    installer: Installer,
    kind: str,
    message: str,
    *,
    from_plan: str | None = None,
    to_plan: str | None = None,
) -> None:
    session.add(
        BillingActivity(
            installer_id=installer.id,
            kind=kind,
            message=message,
            from_plan=from_plan,
            to_plan=to_plan,
        )
    )


def _items(subscription: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return list((subscription.get("items") or {}).get("data") or [])


def _item_price_id(item: Mapping[str, Any]) -> str | None:
    price = item.get("price")
    return price if isinstance(price, str) else (price or {}).get("id")


def _schedule_id(subscription: Mapping[str, Any]) -> str | None:
    schedule = subscription.get("schedule")
    return schedule if isinstance(schedule, str) else (schedule or {}).get("id")


async def _price_row(session: AsyncSession, stripe_price_id: str | None) -> PlanPrice | None:
    if not stripe_price_id:
        return None
    return await session.scalar(
        select(PlanPrice).where(PlanPrice.stripe_price_id == stripe_price_id)
    )


# ---- Applying Stripe state --------------------------------------------------------------


async def _apply_subscription(
    session: AsyncSession,
    installer: Installer,
    subscription: Mapping[str, Any],
    *,
    log: bool = True,
) -> None:
    """Mirror a Stripe subscription onto the installer; only ACTIVE grants a paid plan."""
    status = _STATUS_MAP.get(subscription.get("status", ""), SubscriptionStatus.CANCELED)
    is_current = installer.stripe_subscription_id in (None, subscription["id"])
    if not is_current and status is not SubscriptionStatus.ACTIVE:
        # A late event about a subscription that has since been replaced.
        return

    items = _items(subscription)
    item = items[0] if items else {}
    price_row = await _price_row(session, _item_price_id(item))
    if price_row is None and status is SubscriptionStatus.ACTIVE:
        logger.error(
            "Subscription %s uses a price that is not in the catalogue; treating it as free",
            subscription["id"],
        )
    default_key = registry.default.key
    paid_key = price_row.plan_key if price_row else default_key
    # Newer API versions report the billing period on the item rather than the subscription.
    period_end = subscription.get("current_period_end") or item.get("current_period_end")

    previous_plan = installer.plan
    previous_status = installer.subscription_status
    installer.subscription_status = status
    installer.plan = paid_key if status is SubscriptionStatus.ACTIVE else default_key
    installer.plan_price_id = (
        price_row.id if price_row and status is SubscriptionStatus.ACTIVE else None
    )
    installer.current_period_end = _timestamp(period_end)

    if status is SubscriptionStatus.CANCELED:
        installer.stripe_subscription_id = None
        installer.cancel_at_period_end = False
        installer.pending_plan = None
        installer.stripe_schedule_id = None
        installer.plan_price_id = None
    else:
        installer.stripe_subscription_id = subscription["id"]
        installer.cancel_at_period_end = bool(
            subscription.get("cancel_at_period_end") or subscription.get("cancel_at")
        )
        schedule_id = _schedule_id(subscription)
        if schedule_id is None:
            installer.stripe_schedule_id = None
            installer.pending_plan = None
        else:
            installer.stripe_schedule_id = schedule_id
            if installer.pending_plan == installer.plan:
                # The booked downgrade has taken effect.
                installer.pending_plan = None

    if not log:
        return
    if status is SubscriptionStatus.CANCELED and previous_status is not SubscriptionStatus.CANCELED:
        _log(
            session,
            installer,
            "ended",
            f"Subscription ended. Back on the {_plan_name(default_key)} plan.",
            from_plan=previous_plan,
            to_plan=installer.plan,
        )
    elif installer.plan != previous_plan:
        if previous_plan == default_key and previous_status is SubscriptionStatus.PAST_DUE:
            message = f"Payment received. The {_plan_name(installer.plan)} plan is back."
            kind = "plan_restored"
        elif previous_plan == default_key:
            message = f"Subscribed to the {_plan_name(installer.plan)} plan."
            kind = "subscribed"
        elif installer.plan == default_key:
            message = f"Moved to the {_plan_name(installer.plan)} plan."
            kind = "plan_changed"
        else:
            message = f"Changed from {_plan_name(previous_plan)} to {_plan_name(installer.plan)}."
            kind = "plan_changed"
        _log(session, installer, kind, message, from_plan=previous_plan, to_plan=installer.plan)


async def _upsert_invoice(
    session: AsyncSession, installer: Installer, invoice: Mapping[str, Any]
) -> BillingInvoice | None:
    """Store (or refresh) a Stripe invoice for the installer's payment history."""
    invoice_id = invoice.get("id")
    status = invoice.get("status")
    if not invoice_id or not status:
        return None

    lines = list((invoice.get("lines") or {}).get("data") or [])
    first_line = lines[0] if lines else {}
    period = first_line.get("period") or {}
    transitions = invoice.get("status_transitions") or {}
    plan_name = await _plan_name_for_line(session, first_line)

    values = {
        "number": invoice.get("number"),
        "status": status,
        "description": (first_line.get("description") or "")[:300] or None,
        "plan_name": plan_name,
        "amount_due_pence": int(invoice.get("amount_due") or 0),
        "amount_paid_pence": int(invoice.get("amount_paid") or 0),
        "currency": str(invoice.get("currency") or "gbp")[:3],
        "billing_reason": invoice.get("billing_reason"),
        "hosted_invoice_url": invoice.get("hosted_invoice_url"),
        "invoice_pdf_url": invoice.get("invoice_pdf"),
        "period_start": _timestamp(period.get("start") or invoice.get("period_start")),
        "period_end": _timestamp(period.get("end") or invoice.get("period_end")),
        "paid_at": _timestamp(transitions.get("paid_at")),
    }
    existing = await session.get(BillingInvoice, invoice_id)
    if existing is None:
        row = BillingInvoice(
            id=invoice_id,
            installer_id=installer.id,
            issued_at=_timestamp(invoice.get("created")) or utcnow(),
            **values,
        )
        session.add(row)
        return row
    if _INVOICE_STATUS_RANK.get(status, 0) >= _INVOICE_STATUS_RANK.get(existing.status, 0):
        for name, value in values.items():
            # Never blank out something we already know (e.g. when a thin payload omits it).
            if value is not None:
                setattr(existing, name, value)
    return existing


async def _plan_name_for_line(session: AsyncSession, line: Mapping[str, Any]) -> str | None:
    """The plan an invoice line was for, from its Stripe price (either API shape)."""
    price = line.get("price")
    price_id = price if isinstance(price, str) else (price or {}).get("id")
    if not price_id:
        details = (line.get("pricing") or {}).get("price_details") or {}
        price = details.get("price")
        price_id = price if isinstance(price, str) else (price or {}).get("id")
    if not price_id:
        return None
    return await session.scalar(
        select(Plan.name)
        .join(PlanPrice, PlanPrice.plan_key == Plan.key)
        .where(PlanPrice.stripe_price_id == price_id)
    )


async def _record_invoice_of(
    session: AsyncSession, installer: Installer, subscription: Mapping[str, Any]
) -> None:
    latest = subscription.get("latest_invoice")
    if isinstance(latest, Mapping):
        await _upsert_invoice(session, installer, latest)


# ---- Checkout ---------------------------------------------------------------------------


async def create_checkout_session(
    session: AsyncSession,
    installer: Installer,
    email: str,
    plan_key: str,
    gateway: BillingGateway,
    return_to: str = "dashboard",
) -> str:
    """Start a subscription checkout, creating the Stripe customer on first use."""
    _require_configured()
    if _is_live(installer):
        raise AlreadySubscribedError
    price = await plan_service.ensure_stripe_price(session, plan_key, gateway)

    if installer.stripe_customer_id is None:
        installer.stripe_customer_id = await call_stripe(
            gateway.create_customer(
                email=email, name=installer.business_name, installer_id=str(installer.id)
            )
        )
        await session.commit()

    success_url, cancel_url, _ = _return_urls(return_to)
    return await call_stripe(
        gateway.create_checkout_session(
            customer_id=installer.stripe_customer_id,
            price_id=price.stripe_price_id or "",
            installer_id=str(installer.id),
            plan_key=plan_key,
            success_url=success_url,
            cancel_url=cancel_url,
        )
    )


async def checkout_status(
    session: AsyncSession, installer: Installer, session_id: str, gateway: BillingGateway
) -> CheckoutStatus:
    """Where a returning checkout stands, granting the plan now if the payment went through.

    The webhook normally does this too; doing it here as well means the installer sees their
    new plan the moment they return, and it still works while the webhook is being set up.
    """
    _require_configured()
    checkout = await call_stripe(gateway.get_checkout_session(session_id))
    ours = checkout.get("client_reference_id") == str(installer.id) or (
        installer.stripe_customer_id is not None
        and _customer_id(checkout.get("customer")) == installer.stripe_customer_id
    )
    if not ours:
        raise NotFoundError("This checkout could not be found.", code="checkout_not_found")

    if checkout.get("status") == "expired":
        return CheckoutStatus(state="expired")
    if checkout.get("status") != "complete":
        return CheckoutStatus(state="open")
    if checkout.get("payment_status") not in ("paid", "no_payment_required"):
        # Bank-style payments can still be settling.
        return CheckoutStatus(state="processing")

    subscription = checkout.get("subscription")
    if isinstance(subscription, str):
        subscription = await call_stripe(gateway.get_subscription(subscription))
    if not isinstance(subscription, Mapping):
        return CheckoutStatus(state="processing")

    await _lock(session, installer)
    installer.stripe_customer_id = (
        _customer_id(checkout.get("customer")) or installer.stripe_customer_id
    )
    await _apply_subscription(session, installer, subscription)
    await _record_invoice_of(session, installer, subscription)
    await session.commit()
    if installer.subscription_status is not SubscriptionStatus.ACTIVE:
        return CheckoutStatus(state="processing")
    return CheckoutStatus(
        state="paid", plan=PlanRef(key=installer.plan, name=_plan_name(installer.plan))
    )


def _customer_id(customer: Any) -> str | None:
    return customer if isinstance(customer, str) else (customer or {}).get("id")


async def create_portal_session(
    installer: Installer, gateway: BillingGateway, return_to: str = "dashboard"
) -> str:
    _require_configured()
    if installer.stripe_customer_id is None:
        raise NoBillingAccountError
    return await call_stripe(
        gateway.create_portal_session(
            customer_id=installer.stripe_customer_id, return_url=_return_urls(return_to)[2]
        )
    )


# ---- Changing, cancelling and resuming --------------------------------------------------


async def change_plan(
    session: AsyncSession, installer: Installer, plan_key: str, gateway: BillingGateway
) -> BillingSummary:
    """Move a subscriber to another plan: upgrades now, downgrades at the end of the period."""
    _require_configured()
    await _lock(session, installer)
    if not _is_live(installer):
        raise NoSubscriptionError
    if installer.subscription_status is SubscriptionStatus.PAST_DUE:
        raise PaymentOverdueError

    target = await plan_service.get_plan(session, plan_key)
    if target.key == installer.plan:
        if installer.pending_plan is None:
            raise SamePlanError
        return await cancel_pending_change(session, installer, gateway)
    if target.is_default:
        # Moving to the free plan is a cancellation: it takes effect at the end of the period.
        return await cancel_subscription(session, installer, gateway)

    price = await plan_service.ensure_stripe_price(session, plan_key, gateway)
    subscription = await call_stripe(
        gateway.get_subscription(installer.stripe_subscription_id or "")
    )
    items = _items(subscription)
    if not items:
        raise NoSubscriptionError

    previous = installer.plan
    is_upgrade = target.sort_rank > registry.entry(previous).capabilities.sort_rank
    if installer.stripe_schedule_id:
        await call_stripe(gateway.release_schedule(installer.stripe_schedule_id))
        installer.stripe_schedule_id = None
        installer.pending_plan = None

    if is_upgrade:
        try:
            updated = await gateway.change_price(
                subscription_id=subscription["id"],
                item_id=items[0]["id"],
                price_id=price.stripe_price_id or "",
            )
        except stripe.CardError as exc:
            await session.commit()  # keep our records in step with the schedule released above
            raise PaymentDeclinedError from exc
        except stripe.StripeError as exc:
            logger.exception("Stripe request failed")
            await session.commit()
            raise BillingUnavailableError from exc
        await _apply_subscription(session, installer, updated, log=False)
        await _record_invoice_of(session, installer, updated)
        _log(
            session,
            installer,
            "upgraded",
            f"Upgraded from {_plan_name(previous)} to {target.name}.",
            from_plan=previous,
            to_plan=target.key,
        )
    else:
        if installer.cancel_at_period_end:
            # Choosing a lower plan means they are staying: keep renewing, at the lower price.
            await call_stripe(
                gateway.set_cancel_at_period_end(subscription_id=subscription["id"], cancel=False)
            )
            installer.cancel_at_period_end = False
        schedule = await call_stripe(
            gateway.schedule_price_change(
                subscription_id=subscription["id"], price_id=price.stripe_price_id or ""
            )
        )
        installer.pending_plan = target.key
        installer.stripe_schedule_id = schedule.get("id")
        _log(
            session,
            installer,
            "downgrade_scheduled",
            f"Switch to {target.name} booked for the end of the current period.",
            from_plan=previous,
            to_plan=target.key,
        )
    await session.commit()
    return await summary(session, installer)


async def cancel_pending_change(
    session: AsyncSession, installer: Installer, gateway: BillingGateway
) -> BillingSummary:
    """Drop a booked downgrade: the installer stays on their current plan."""
    _require_configured()
    await _lock(session, installer)
    if installer.stripe_schedule_id is None and installer.pending_plan is None:
        raise NothingToChangeError
    if installer.stripe_schedule_id:
        await call_stripe(gateway.release_schedule(installer.stripe_schedule_id))
    dropped = installer.pending_plan
    installer.stripe_schedule_id = None
    installer.pending_plan = None
    _log(
        session,
        installer,
        "downgrade_cancelled",
        f"Cancelled the switch to {_plan_name(dropped)}. You stay on {_plan_name(installer.plan)}.",
        from_plan=installer.plan,
        to_plan=dropped,
    )
    await session.commit()
    return await summary(session, installer)


async def cancel_subscription(
    session: AsyncSession, installer: Installer, gateway: BillingGateway
) -> BillingSummary:
    """Switch auto-renewal off: the plan runs to the end of the period it is paid for."""
    _require_configured()
    await _lock(session, installer)
    if not _is_live(installer):
        raise NoSubscriptionError
    if installer.cancel_at_period_end:
        return await summary(session, installer)

    if installer.stripe_schedule_id:
        # A subscription attached to a schedule is changed through the schedule.
        await call_stripe(gateway.release_schedule(installer.stripe_schedule_id))
        installer.stripe_schedule_id = None
        installer.pending_plan = None
    updated = await call_stripe(
        gateway.set_cancel_at_period_end(
            subscription_id=installer.stripe_subscription_id or "", cancel=True
        )
    )
    await _apply_subscription(session, installer, updated, log=False)
    installer.cancel_at_period_end = True
    _log(
        session,
        installer,
        "cancel_scheduled",
        "Auto-renewal switched off. Your plan runs until the end of the current period.",
        from_plan=installer.plan,
    )
    await session.commit()
    return await summary(session, installer)


async def resume_subscription(
    session: AsyncSession, installer: Installer, gateway: BillingGateway
) -> BillingSummary:
    """Switch auto-renewal back on before the period ends."""
    _require_configured()
    await _lock(session, installer)
    if not _is_live(installer):
        raise NoSubscriptionError
    if not installer.cancel_at_period_end:
        raise NothingToChangeError
    updated = await call_stripe(
        gateway.set_cancel_at_period_end(
            subscription_id=installer.stripe_subscription_id or "", cancel=False
        )
    )
    await _apply_subscription(session, installer, updated, log=False)
    installer.cancel_at_period_end = False
    _log(
        session,
        installer,
        "resumed",
        "Auto-renewal switched back on.",
        from_plan=installer.plan,
    )
    await session.commit()
    return await summary(session, installer)


# ---- Reading ----------------------------------------------------------------------------


def _options(installer: Installer, *, live: bool) -> list[PlanOption]:
    current = registry.entry(installer.plan)
    options: list[PlanOption] = []
    for entry in registry.all():
        if entry.key == installer.plan:
            action = "current"
        elif entry.is_default:
            if not live:
                continue
            action = "cancel"
        elif not entry.is_purchasable:
            continue
        elif not live:
            action = "subscribe"
        elif entry.capabilities.sort_rank > current.capabilities.sort_rank:
            action = "upgrade"
        else:
            action = "downgrade"
        options.append(_option(entry, action))
    return options


def _option(entry: PlanEntry, action: str) -> PlanOption:
    return PlanOption(
        key=entry.key,
        name=entry.name,
        tagline=entry.tagline,
        features=list(entry.features),
        is_popular=entry.is_popular,
        price_pence=entry.price_pence,
        currency=entry.currency,
        action=action,  # type: ignore[arg-type]
    )


async def summary(session: AsyncSession, installer: Installer) -> BillingSummary:
    """Everything the billing page shows, in one response."""
    live = _is_live(installer)
    past_due = installer.subscription_status is SubscriptionStatus.PAST_DUE
    paying = live and installer.subscription_status is SubscriptionStatus.ACTIVE

    price_pence: int | None = None
    currency = "gbp"
    if paying:
        row = (
            await session.get(PlanPrice, installer.plan_price_id)
            if installer.plan_price_id
            else None
        )
        if row is not None:
            price_pence, currency = row.amount_pence, row.currency
        else:
            entry = registry.entry(installer.plan)
            price_pence, currency = entry.price_pence, entry.currency

    pending = None
    if installer.pending_plan:
        pending = PendingChange(
            plan=PlanRef(key=installer.pending_plan, name=_plan_name(installer.pending_plan)),
            effective_at=installer.current_period_end,
        )

    return BillingSummary(
        billing_enabled=get_settings().stripe_configured,
        plan=PlanRef(key=installer.plan, name=_plan_name(installer.plan)),
        subscription_status=installer.subscription_status,
        has_billing_account=installer.stripe_customer_id is not None,
        has_subscription=live,
        auto_renew=paying and not installer.cancel_at_period_end,
        cancel_at_period_end=live and installer.cancel_at_period_end,
        current_period_end=installer.current_period_end if live else None,
        price_pence=price_pence,
        currency=currency,
        pending_change=pending,
        payment_failed=past_due,
        options=[] if past_due else _options(installer, live=live),
    )


async def list_invoices(
    session: AsyncSession, installer_id: uuid.UUID, *, offset: int, limit: int
) -> tuple[Sequence[BillingInvoice], int]:
    where = BillingInvoice.installer_id == installer_id
    total = await session.scalar(select(func.count()).select_from(BillingInvoice).where(where))
    rows = await session.scalars(
        select(BillingInvoice)
        .where(where)
        .order_by(BillingInvoice.issued_at.desc(), BillingInvoice.id)
        .offset(offset)
        .limit(limit)
    )
    return rows.all(), total or 0


async def list_activity(
    session: AsyncSession, installer_id: uuid.UUID, *, limit: int = 20
) -> Sequence[BillingActivity]:
    rows = await session.scalars(
        select(BillingActivity)
        .where(BillingActivity.installer_id == installer_id)
        .order_by(BillingActivity.created_at.desc())
        .limit(limit)
    )
    return rows.all()


@dataclass(frozen=True, slots=True)
class AdminInvoiceRow:
    invoice: BillingInvoice
    business_name: str


async def list_all_invoices(
    session: AsyncSession,
    *,
    status: str | None,
    search: str | None,
    installer_id: uuid.UUID | None,
    offset: int,
    limit: int,
) -> tuple[list[AdminInvoiceRow], int]:
    """Every installer's invoices, newest first, for the team's Payments page."""
    filters = []
    if status:
        filters.append(BillingInvoice.status == status)
    if installer_id:
        filters.append(BillingInvoice.installer_id == installer_id)
    if search:
        like = f"%{search.strip()}%"
        filters.append(Installer.business_name.ilike(like) | BillingInvoice.number.ilike(like))
    base = select(BillingInvoice, Installer.business_name).join(
        Installer, Installer.id == BillingInvoice.installer_id
    )
    total = await session.scalar(
        select(func.count())
        .select_from(BillingInvoice)
        .join(Installer, Installer.id == BillingInvoice.installer_id)
        .where(*filters)
    )
    rows = await session.execute(
        base.where(*filters)
        .order_by(BillingInvoice.issued_at.desc(), BillingInvoice.id)
        .offset(offset)
        .limit(limit)
    )
    return [AdminInvoiceRow(invoice, name) for invoice, name in rows.all()], total or 0


async def payments_overview(session: AsyncSession) -> PaymentsOverview:
    active = (
        Installer.subscription_status == SubscriptionStatus.ACTIVE,
        Installer.stripe_subscription_id.is_not(None),
    )
    count, monthly = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(PlanPrice.amount_pence), 0))
            .select_from(Installer)
            .outerjoin(PlanPrice, Installer.plan_price_id == PlanPrice.id)
            .where(*active)
        )
    ).one()
    past_due = await session.scalar(
        select(func.count())
        .select_from(Installer)
        .where(Installer.subscription_status == SubscriptionStatus.PAST_DUE)
    )
    cancelling = await session.scalar(
        select(func.count()).select_from(Installer).where(*active, Installer.cancel_at_period_end)
    )
    paid = await session.scalar(
        select(func.coalesce(func.sum(BillingInvoice.amount_paid_pence), 0)).where(
            BillingInvoice.status == "paid",
            BillingInvoice.paid_at >= utcnow() - timedelta(days=30),
        )
    )
    return PaymentsOverview(
        active_subscriptions=count,
        monthly_recurring_pence=int(monthly),
        past_due=past_due or 0,
        cancelling=cancelling or 0,
        paid_last_30_days_pence=int(paid or 0),
    )


# ---- Webhooks ---------------------------------------------------------------------------


def verify_webhook(payload: bytes, signature: str | None) -> dict[str, Any]:
    """Check the `Stripe-Signature` header against the raw body and return the event."""
    secret = get_settings().stripe_webhook_secret
    if secret is None:
        raise ServiceNotConfiguredError
    try:
        stripe.WebhookSignature.verify_header(
            payload, signature, secret, tolerance=_WEBHOOK_TOLERANCE_SECONDS
        )
        event = json.loads(payload)
    except (stripe.SignatureVerificationError, ValueError) as exc:
        raise InvalidWebhookError from exc
    if not isinstance(event, dict) or "id" not in event or "type" not in event:
        raise InvalidWebhookError
    return event


async def handle_event(
    session: AsyncSession, event: Mapping[str, Any], gateway: BillingGateway
) -> list[emails.Email]:
    """Apply a verified Stripe event exactly once; returns any emails to send.

    The event id is recorded in the same transaction as its effects, so a redelivery (or a
    concurrent duplicate) is a no-op and a failure is retried by Stripe.
    """
    recorded = await session.scalar(
        insert(StripeEvent)
        .values(id=event["id"], type=event["type"], processed_at=utcnow())
        .on_conflict_do_nothing(index_elements=[StripeEvent.id])
        .returning(StripeEvent.id)
    )
    if recorded is None:
        await session.rollback()
        return []

    kind = event["type"]
    payload = event["data"]["object"]
    outbox: list[emails.Email] = []
    if kind == "checkout.session.completed":
        await _on_checkout_completed(session, payload, gateway)
    elif kind in _SUBSCRIPTION_EVENTS:
        await _on_subscription_changed(session, payload, gateway, deleted=kind.endswith(".deleted"))
    elif kind in _SCHEDULE_EVENTS:
        await _on_schedule_changed(session, payload)
    elif kind in _INVOICE_EVENTS:
        outbox = await _on_invoice(session, payload, failed=kind == "invoice.payment_failed")
    await session.commit()
    return outbox


async def _installer_for(
    session: AsyncSession, *, installer_id: str | None, customer_id: str | None
) -> Installer | None:
    """Find (and lock) the installer an event concerns: by our id, else by Stripe customer."""
    by_id = _parse_uuid(installer_id)
    if by_id is not None:
        installer = await session.get(Installer, by_id, with_for_update=True)
        if installer is not None:
            return installer
    if customer_id:
        return await session.scalar(
            select(Installer).where(Installer.stripe_customer_id == customer_id).with_for_update()
        )
    return None


async def _on_checkout_completed(
    session: AsyncSession, checkout: Mapping[str, Any], gateway: BillingGateway
) -> None:
    subscription_id = _customer_id(checkout.get("subscription"))
    installer = await _installer_for(
        session,
        installer_id=checkout.get("client_reference_id"),
        customer_id=_customer_id(checkout.get("customer")),
    )
    if installer is None or not subscription_id:
        logger.warning("checkout.session.completed without a known installer or subscription")
        return
    installer.stripe_customer_id = (
        _customer_id(checkout.get("customer")) or installer.stripe_customer_id
    )
    # Fetch the subscription so the plan is granted now, whatever order events arrive in.
    subscription = await call_stripe(gateway.get_subscription(subscription_id))
    await _apply_subscription(session, installer, subscription)
    await _record_invoice_of(session, installer, subscription)


async def _on_subscription_changed(
    session: AsyncSession,
    payload: Mapping[str, Any],
    gateway: BillingGateway,
    *,
    deleted: bool,
) -> None:
    installer = await _installer_for(
        session,
        installer_id=(payload.get("metadata") or {}).get("installer_id"),
        customer_id=_customer_id(payload.get("customer")),
    )
    if installer is None:
        logger.warning("Subscription event for an unknown installer")
        return
    # Events can arrive out of order, so act on the subscription as it is now. A deleted
    # subscription cannot change any more: its event already says everything.
    subscription = (
        payload if deleted else await call_stripe(gateway.get_subscription(payload["id"]))
    )
    await _apply_subscription(session, installer, subscription)
    await _record_invoice_of(session, installer, subscription)


async def _on_schedule_changed(session: AsyncSession, schedule: Mapping[str, Any]) -> None:
    """Track a booked downgrade, including ones made in the Stripe billing portal."""
    installer = await _installer_for(
        session,
        installer_id=None,
        customer_id=_customer_id(schedule.get("customer")),
    )
    if installer is None:
        return
    subscription_id = _customer_id(schedule.get("subscription"))
    if subscription_id and installer.stripe_subscription_id not in (None, subscription_id):
        return

    if schedule.get("status") not in ("not_started", "active"):
        if installer.stripe_schedule_id == schedule.get("id"):
            installer.stripe_schedule_id = None
            installer.pending_plan = None
        return

    installer.stripe_schedule_id = schedule["id"]
    phases = schedule.get("phases") or []
    pending_key = None
    if len(phases) > 1:
        next_items = phases[1].get("items") or []
        row = await _price_row(session, _item_price_id(next_items[0])) if next_items else None
        pending_key = row.plan_key if row else None
    if pending_key and pending_key != installer.plan:
        installer.pending_plan = pending_key
    elif len(phases) <= 1:
        installer.pending_plan = None


async def _on_invoice(
    session: AsyncSession, invoice: Mapping[str, Any], *, failed: bool
) -> list[emails.Email]:
    installer = await _installer_for(
        session, installer_id=None, customer_id=_customer_id(invoice.get("customer"))
    )
    if installer is None:
        return []
    await _upsert_invoice(session, installer, invoice)
    if not failed or installer.subscription_status is not SubscriptionStatus.ACTIVE:
        return []

    previous = installer.plan
    installer.subscription_status = SubscriptionStatus.PAST_DUE
    installer.plan = registry.default.key
    _log(
        session,
        installer,
        "payment_failed",
        f"A payment failed. The {_plan_name(previous)} plan is paused until it is paid.",
        from_plan=previous,
        to_plan=installer.plan,
    )
    user_email = await _login_email(session, installer)
    if user_email is None:
        return []
    return [emails.payment_failed(installer, user_email, previous_plan=_plan_name(previous))]


async def _login_email(session: AsyncSession, installer: Installer) -> str | None:
    if installer.user_id is None:
        return None
    return await session.scalar(select(User.email).where(User.id == installer.user_id))
