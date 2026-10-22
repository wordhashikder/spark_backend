"""Every Stripe network call, behind a protocol so tests can stub them.

Methods take and return plain values or mappings (`to_dict()` of the Stripe object), so
nothing outside this module depends on the SDK's types.
"""

import logging
from collections.abc import Awaitable, Mapping
from typing import Any, Protocol

import stripe

from app.core.config import Settings
from app.core.exceptions import ServiceNotConfiguredError, ServiceUnavailableError

logger = logging.getLogger(__name__)


class BillingUnavailableError(ServiceUnavailableError):
    code = "billing_unavailable"
    message = "Billing is temporarily unavailable. Please try again shortly."


class BillingGateway(Protocol):
    # ---- Catalogue ---------------------------------------------------------------------

    async def upsert_product(
        self, *, product_id: str | None, key: str, name: str, description: str | None
    ) -> str:
        """Create or update the Stripe product behind a plan; returns its id."""
        ...

    async def archive_product(self, product_id: str) -> None: ...

    async def create_price(
        self, *, product_id: str, key: str, amount_pence: int, currency: str, interval: str
    ) -> str:
        """Create a recurring price (prices cannot be edited) and return its id."""
        ...

    async def archive_price(self, price_id: str) -> None:
        """Stop a price being used for new subscriptions; existing ones keep paying it."""
        ...

    # ---- Customers and checkout --------------------------------------------------------

    async def create_customer(self, *, email: str, name: str, installer_id: str) -> str: ...

    async def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        installer_id: str,
        plan_key: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
        """Create a subscription Checkout Session and return its URL."""
        ...

    async def get_checkout_session(self, session_id: str) -> Mapping[str, Any]:
        """A Checkout Session with its subscription (and that subscription's latest invoice)."""
        ...

    async def create_portal_session(self, *, customer_id: str, return_url: str) -> str: ...

    # ---- Subscriptions -----------------------------------------------------------------

    async def get_subscription(self, subscription_id: str) -> Mapping[str, Any]:
        """A subscription with its latest invoice expanded."""
        ...

    async def change_price(
        self, *, subscription_id: str, item_id: str, price_id: str
    ) -> Mapping[str, Any]:
        """Swap the price now: charge the prorated difference immediately or fail unchanged."""
        ...

    async def set_cancel_at_period_end(
        self, *, subscription_id: str, cancel: bool
    ) -> Mapping[str, Any]: ...

    async def schedule_price_change(
        self, *, subscription_id: str, price_id: str
    ) -> Mapping[str, Any]:
        """Book a price change for the end of the current period; returns the schedule."""
        ...

    async def release_schedule(self, schedule_id: str) -> None:
        """Detach a schedule from its subscription, leaving the subscription as it is now."""
        ...


class StripeGateway:
    """`BillingGateway` backed by the Stripe SDK's async client methods."""

    def __init__(self, settings: Settings) -> None:
        if settings.stripe_secret_key is None:
            raise ServiceNotConfiguredError
        self._client = stripe.StripeClient(settings.stripe_secret_key, max_network_retries=2)

    # ---- Catalogue ---------------------------------------------------------------------

    async def upsert_product(
        self, *, product_id: str | None, key: str, name: str, description: str | None
    ) -> str:
        metadata = {"plan_key": key}
        if product_id is not None:
            # An empty description clears it on Stripe's side.
            await self._client.v1.products.update_async(
                product_id, {"name": name, "description": description or "", "metadata": metadata}
            )
            return product_id
        params: dict[str, Any] = {"name": name, "metadata": metadata}
        if description:
            params["description"] = description
        product = await self._client.v1.products.create_async(
            params, {"idempotency_key": f"plan-product-{key}"}
        )
        return product.id

    async def archive_product(self, product_id: str) -> None:
        await self._client.v1.products.update_async(product_id, {"active": False})

    async def create_price(
        self, *, product_id: str, key: str, amount_pence: int, currency: str, interval: str
    ) -> str:
        price = await self._client.v1.prices.create_async(
            {
                "product": product_id,
                "unit_amount": amount_pence,
                "currency": currency,
                "recurring": {"interval": interval},
                "metadata": {"plan_key": key},
            }
        )
        return price.id

    async def archive_price(self, price_id: str) -> None:
        await self._client.v1.prices.update_async(price_id, {"active": False})

    # ---- Customers and checkout --------------------------------------------------------

    async def create_customer(self, *, email: str, name: str, installer_id: str) -> str:
        customer = await self._client.v1.customers.create_async(
            {"email": email, "name": name, "metadata": {"installer_id": installer_id}},
            # Concurrent checkout attempts must not create two customers for one installer.
            {"idempotency_key": f"installer-customer-{installer_id}"},
        )
        return customer.id

    async def create_checkout_session(
        self,
        *,
        customer_id: str,
        price_id: str,
        installer_id: str,
        plan_key: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
        metadata = {"installer_id": installer_id, "plan": plan_key}
        checkout = await self._client.v1.checkout.sessions.create_async(
            {
                "mode": "subscription",
                "customer": customer_id,
                "line_items": [{"price": price_id, "quantity": 1}],
                "client_reference_id": installer_id,
                "metadata": metadata,
                "subscription_data": {"metadata": metadata},
                "success_url": success_url,
                "cancel_url": cancel_url,
                "allow_promotion_codes": True,
            }
        )
        if checkout.url is None:
            raise BillingUnavailableError
        return checkout.url

    async def get_checkout_session(self, session_id: str) -> Mapping[str, Any]:
        checkout = await self._client.v1.checkout.sessions.retrieve_async(
            session_id, {"expand": ["subscription.latest_invoice"]}
        )
        return checkout.to_dict()

    async def create_portal_session(self, *, customer_id: str, return_url: str) -> str:
        portal = await self._client.v1.billing_portal.sessions.create_async(
            {"customer": customer_id, "return_url": return_url}
        )
        return portal.url

    # ---- Subscriptions -----------------------------------------------------------------

    async def get_subscription(self, subscription_id: str) -> Mapping[str, Any]:
        subscription = await self._client.v1.subscriptions.retrieve_async(
            subscription_id, {"expand": ["latest_invoice"]}
        )
        return subscription.to_dict()

    async def change_price(
        self, *, subscription_id: str, item_id: str, price_id: str
    ) -> Mapping[str, Any]:
        subscription = await self._client.v1.subscriptions.update_async(
            subscription_id,
            {
                "items": [{"id": item_id, "price": price_id}],
                # Credit the unused time on the old price and bill the new one now.
                "proration_behavior": "always_invoice",
                # If the card is declined nothing changes and Stripe raises an error.
                "payment_behavior": "error_if_incomplete",
                "cancel_at_period_end": False,
                "expand": ["latest_invoice"],
            },
        )
        return subscription.to_dict()

    async def set_cancel_at_period_end(
        self, *, subscription_id: str, cancel: bool
    ) -> Mapping[str, Any]:
        subscription = await self._client.v1.subscriptions.update_async(
            subscription_id, {"cancel_at_period_end": cancel}
        )
        return subscription.to_dict()

    async def schedule_price_change(
        self, *, subscription_id: str, price_id: str
    ) -> Mapping[str, Any]:
        created = await self._client.v1.subscription_schedules.create_async(
            {"from_subscription": subscription_id}
        )
        # Plain mappings throughout: on Stripe objects `.items` is dict.items, not the field.
        schedule = created.to_dict()
        current = schedule["phases"][0]
        updated = await self._client.v1.subscription_schedules.update_async(
            schedule["id"],
            {
                "end_behavior": "release",
                "phases": [
                    {
                        "items": [
                            {"price": _price_id_of(item), "quantity": item.get("quantity") or 1}
                            for item in current["items"]
                        ],
                        "start_date": current["start_date"],
                        "end_date": current["end_date"],
                    },
                    {
                        "items": [{"price": price_id, "quantity": 1}],
                        # One period on the new price, then the schedule releases and the
                        # subscription simply carries on at it.
                        "duration": {"interval": "month", "interval_count": 1},
                        "proration_behavior": "none",
                    },
                ],
            },
        )
        return updated.to_dict()

    async def release_schedule(self, schedule_id: str) -> None:
        await self._client.v1.subscription_schedules.release_async(schedule_id)


def _price_id_of(item: Mapping[str, Any]) -> str:
    price = item["price"]
    return price if isinstance(price, str) else price["id"]


class UnconfiguredGateway:
    """Stands in when Stripe is not configured: every call reports 503."""

    async def _unavailable(self, *_: Any, **__: Any) -> Any:
        raise ServiceNotConfiguredError

    upsert_product = archive_product = create_price = archive_price = _unavailable
    create_customer = _unavailable
    create_checkout_session = get_checkout_session = create_portal_session = _unavailable
    get_subscription = change_price = set_cancel_at_period_end = _unavailable
    schedule_price_change = release_schedule = _unavailable


async def call_stripe[T](operation: Awaitable[T]) -> T:
    """Await a gateway call, turning Stripe failures into a 503 without leaking details."""
    try:
        return await operation
    except stripe.StripeError as exc:
        logger.exception("Stripe request failed")
        raise BillingUnavailableError from exc


def build_gateway(settings: Settings) -> BillingGateway:
    return StripeGateway(settings) if settings.stripe_configured else UnconfiguredGateway()
