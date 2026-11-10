"""The real Stripe gateway's catalogue behaviour, against a stubbed SDK client."""

from types import SimpleNamespace
from typing import Any

import stripe

from app.core.config import Settings
from app.services.stripe_gateway import StripeGateway


class _Products:
    def __init__(self, *, known: set[str]) -> None:
        self.known = known
        self.updated: list[str] = []
        self.created: list[tuple[dict[str, Any], dict[str, Any] | None]] = []

    async def update_async(self, product_id: str, params: dict[str, Any]) -> None:
        if product_id not in self.known:
            raise stripe.InvalidRequestError(
                f"No such product: '{product_id}'", "id", code="resource_missing"
            )
        self.updated.append(product_id)

    async def create_async(self, params: dict[str, Any], options: dict[str, Any] | None = None):
        self.created.append((params, options))
        return SimpleNamespace(id="prod_live_1")


def _gateway(products: _Products) -> StripeGateway:
    gateway = StripeGateway(Settings(stripe_secret_key="sk_test_x", _env_file=None))
    gateway._client = SimpleNamespace(v1=SimpleNamespace(products=products))  # type: ignore[assignment]
    return gateway


async def test_a_known_product_is_updated_in_place():
    products = _Products(known={"prod_a"})
    result = await _gateway(products).upsert_product(
        product_id="prod_a", key="pro", name="Pro", description=None
    )
    assert (result, products.updated, products.created) == ("prod_a", ["prod_a"], [])


async def test_a_product_stripe_does_not_know_is_created_again():
    products = _Products(known=set())
    result = await _gateway(products).upsert_product(
        product_id="prod_from_test_mode", key="pro", name="Pro", description="Tag"
    )
    assert result == "prod_live_1"
    ((params, options),) = products.created
    assert params["name"] == "Pro"
    assert options is None  # not the first-creation idempotency key


async def test_other_stripe_errors_still_propagate():
    class Denied(_Products):
        async def update_async(self, product_id: str, params: dict[str, Any]) -> None:
            raise stripe.PermissionError("no permission")

    products = Denied(known={"prod_a"})
    try:
        await _gateway(products).upsert_product(
            product_id="prod_a", key="pro", name="Pro", description=None
        )
    except stripe.PermissionError:
        pass
    else:
        raise AssertionError("the permission error must not be swallowed")
    assert products.created == []
