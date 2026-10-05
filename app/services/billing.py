"""Subscriptions: Stripe Checkout, the billing portal and webhook processing.

Every Stripe network call sits behind `BillingGateway` so tests can stub it.
"""

import json
import logging
import uuid
from collections.abc import Awaitable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

import stripe
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.enums import Plan, SubscriptionStatus
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ServiceNotConfiguredError,
    ServiceUnavailableError,
)
from app.models import Installer, StripeEvent
from app.models.base import utcnow

logger = logging.getLogger(__name__)

_WEBHOOK_TOLERANCE_SECONDS = 300
_SUBSCRIPTION_EVENTS = frozenset(
    {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }
)
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


class AlreadySubscribedError(ConflictError):
    code = "already_subscribed"
    message = "You already have a subscription. Manage it from the billing portal."


class NoBillingAccountError(ConflictError):
    code = "no_billing_account"
    message = "There is no billing account for this installer yet."


class InvalidWebhookError(BadRequestError):
    code = "invalid_webhook"
    message = "The webhook could not be verified."


class BillingUnavailableError(ServiceUnavailableError):
    code = "billing_unavailable"
    message = "Billing is temporarily unavailable. Please try again shortly."


class BillingGateway(Protocol):
    async def create_customer(self, *, email: str, name: str, installer_id: str) -> str:
        """Create a customer and return its id."""
        ...

    async def create_checkout_session(
        self, *, customer_id: str, price_id: str, installer_id: str, plan: Plan
    ) -> str:
        """Create a subscription Checkout Session and return its URL."""
        ...

    async def create_portal_session(self, *, customer_id: str) -> str:
        """Create a Billing Portal session and return its URL."""
        ...

    async def get_subscription(self, subscription_id: str) -> Mapping[str, Any]:
        """Fetch a subscription as a plain mapping."""
        ...


class StripeGateway:
    """`BillingGateway` backed by the Stripe SDK's async client methods."""

    def __init__(self, settings: Settings) -> None:
        if settings.stripe_secret_key is None:
            raise ServiceNotConfiguredError
        self._client = stripe.StripeClient(settings.stripe_secret_key, max_network_retries=2)
        self._account_url = f"{settings.frontend_url}/installer/account"

    async def create_customer(self, *, email: str, name: str, installer_id: str) -> str:
        customer = await self._client.v1.customers.create_async(
            {"email": email, "name": name, "metadata": {"installer_id": installer_id}},
            # Concurrent checkout attempts must not create two customers for one installer.
            {"idempotency_key": f"installer-customer-{installer_id}"},
        )
        return customer.id

    async def create_checkout_session(
        self, *, customer_id: str, price_id: str, installer_id: str, plan: Plan
    ) -> str:
        metadata = {"installer_id": installer_id, "plan": plan.value}
        checkout = await self._client.v1.checkout.sessions.create_async(
            {
                "mode": "subscription",
                "customer": customer_id,
                "line_items": [{"price": price_id, "quantity": 1}],
                "client_reference_id": installer_id,
                "metadata": metadata,
                "subscription_data": {"metadata": metadata},
                "success_url": f"{self._account_url}?checkout=success",
                "cancel_url": f"{self._account_url}?checkout=cancelled",
                "allow_promotion_codes": True,
            }
        )
        if checkout.url is None:
            raise BillingUnavailableError
        return checkout.url

    async def create_portal_session(self, *, customer_id: str) -> str:
        portal = await self._client.v1.billing_portal.sessions.create_async(
            {"customer": customer_id, "return_url": self._account_url}
        )
        return portal.url

    async def get_subscription(self, subscription_id: str) -> Mapping[str, Any]:
        subscription = await self._client.v1.subscriptions.retrieve_async(subscription_id)
        return subscription.to_dict()


class UnconfiguredGateway:
    """Stands in when Stripe is not configured: every call reports 503."""

    async def create_customer(self, *, email: str, name: str, installer_id: str) -> str:
        raise ServiceNotConfiguredError

    async def create_checkout_session(
        self, *, customer_id: str, price_id: str, installer_id: str, plan: Plan
    ) -> str:
        raise ServiceNotConfiguredError

    async def create_portal_session(self, *, customer_id: str) -> str:
        raise ServiceNotConfiguredError

    async def get_subscription(self, subscription_id: str) -> Mapping[str, Any]:
        raise ServiceNotConfiguredError


def build_gateway(settings: Settings) -> BillingGateway:
    return StripeGateway(settings) if settings.stripe_configured else UnconfiguredGateway()


def _price_id(plan: Plan) -> str:
    settings = get_settings()
    prices = {Plan.PRO: settings.stripe_price_pro, Plan.PREMIUM: settings.stripe_price_premium}
    price_id = prices.get(plan)
    if not settings.stripe_configured or price_id is None:
        raise ServiceNotConfiguredError
    return price_id


async def _call_stripe[T](operation: Awaitable[T]) -> T:
    """Await a gateway call, turning Stripe failures into a 503 without leaking details."""
    try:
        return await operation
    except stripe.StripeError as exc:
        logger.exception("Stripe request failed")
        raise BillingUnavailableError from exc


async def create_checkout_session(
    session: AsyncSession, installer: Installer, email: str, plan: Plan, gateway: BillingGateway
) -> str:
    """Start a subscription checkout, creating the Stripe customer on first use."""
    price_id = _price_id(plan)
    if installer.subscription_status in _LIVE_SUBSCRIPTION_STATUSES:
        raise AlreadySubscribedError

    if installer.stripe_customer_id is None:
        installer.stripe_customer_id = await _call_stripe(
            gateway.create_customer(
                email=email, name=installer.business_name, installer_id=str(installer.id)
            )
        )
        await session.commit()

    return await _call_stripe(
        gateway.create_checkout_session(
            customer_id=installer.stripe_customer_id,
            price_id=price_id,
            installer_id=str(installer.id),
            plan=plan,
        )
    )


async def create_portal_session(installer: Installer, gateway: BillingGateway) -> str:
    if not get_settings().stripe_configured:
        raise ServiceNotConfiguredError
    if installer.stripe_customer_id is None:
        raise NoBillingAccountError
    return await _call_stripe(
        gateway.create_portal_session(customer_id=installer.stripe_customer_id)
    )


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
) -> None:
    """Apply a verified Stripe event exactly once.

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
        return

    kind = event["type"]
    payload = event["data"]["object"]
    if kind == "checkout.session.completed":
        await _on_checkout_completed(session, payload, gateway)
    elif kind in _SUBSCRIPTION_EVENTS:
        await _on_subscription_changed(session, payload)
    elif kind == "invoice.payment_failed":
        await _on_payment_failed(session, payload)
    await session.commit()


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


def _parse_uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


async def _on_checkout_completed(
    session: AsyncSession, checkout: Mapping[str, Any], gateway: BillingGateway
) -> None:
    subscription_id = checkout.get("subscription")
    installer = await _installer_for(
        session,
        installer_id=checkout.get("client_reference_id"),
        customer_id=checkout.get("customer"),
    )
    if installer is None or not subscription_id:
        logger.warning("checkout.session.completed without a known installer or subscription")
        return
    installer.stripe_customer_id = checkout.get("customer") or installer.stripe_customer_id
    # Fetch the subscription so the plan is granted now, whatever order events arrive in.
    subscription = await _call_stripe(gateway.get_subscription(subscription_id))
    _apply_subscription(installer, subscription)


async def _on_subscription_changed(session: AsyncSession, subscription: Mapping[str, Any]) -> None:
    installer = await _installer_for(
        session,
        installer_id=(subscription.get("metadata") or {}).get("installer_id"),
        customer_id=subscription.get("customer"),
    )
    if installer is None:
        logger.warning("Subscription event for an unknown installer")
        return
    _apply_subscription(installer, subscription)


async def _on_payment_failed(session: AsyncSession, invoice: Mapping[str, Any]) -> None:
    installer = await _installer_for(
        session, installer_id=None, customer_id=invoice.get("customer")
    )
    if installer is None or installer.subscription_status is not SubscriptionStatus.ACTIVE:
        return
    installer.subscription_status = SubscriptionStatus.PAST_DUE
    installer.plan = Plan.FREE


def _apply_subscription(installer: Installer, subscription: Mapping[str, Any]) -> None:
    """Mirror a Stripe subscription onto the installer; only ACTIVE grants a paid plan."""
    status = _STATUS_MAP.get(subscription.get("status", ""), SubscriptionStatus.CANCELED)
    is_current = installer.stripe_subscription_id in (None, subscription["id"])
    if not is_current and status is not SubscriptionStatus.ACTIVE:
        # A late event about a subscription that has since been replaced.
        return

    item = (subscription.get("items") or {}).get("data", [{}])[0]
    plan = _plan_for_price((item.get("price") or {}).get("id"))
    # Newer API versions report the billing period on the item rather than the subscription.
    period_end = subscription.get("current_period_end") or item.get("current_period_end")

    installer.subscription_status = status
    installer.plan = plan if status is SubscriptionStatus.ACTIVE else Plan.FREE
    installer.current_period_end = datetime.fromtimestamp(period_end, UTC) if period_end else None
    if status is SubscriptionStatus.CANCELED:
        installer.stripe_subscription_id = None
    else:
        installer.stripe_subscription_id = subscription["id"]


def _plan_for_price(price_id: str | None) -> Plan:
    settings = get_settings()
    plans = {settings.stripe_price_pro: Plan.PRO, settings.stripe_price_premium: Plan.PREMIUM}
    plan = plans.get(price_id)
    if plan is None:
        logger.error("Subscription uses an unknown price id %s; treating it as free", price_id)
        return Plan.FREE
    return plan
