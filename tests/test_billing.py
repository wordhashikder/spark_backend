"""Stripe checkout, the billing portal and webhook processing."""

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Plan, SubscriptionStatus
from app.models import Installer, StripeEvent
from tests.helpers import (
    Fakes,
    auth_headers,
    create_installer,
    signed_stripe_event,
    subscription_object,
)

WEBHOOK = "/api/v1/billing/webhook"
PRO, PREMIUM = "price_pro_test", "price_premium_test"


async def _reload(db: AsyncSession, installer: Installer) -> Installer:
    await db.refresh(installer)
    return installer


async def test_checkout_creates_one_customer_and_returns_the_stripe_url(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_installer(db, "Upgrading Electrical", plan=Plan.FREE)
    headers = auth_headers(installer.user)

    assert (
        await client.post("/api/v1/billing/checkout-session", json={"plan": "pro"})
    ).status_code == 401
    free = await client.post(
        "/api/v1/billing/checkout-session", headers=headers, json={"plan": "free"}
    )
    assert free.status_code == 422

    first = await client.post(
        "/api/v1/billing/checkout-session", headers=headers, json={"plan": "pro"}
    )
    assert first.status_code == 200, first.text
    assert first.json() == {"url": "https://checkout.stripe.test/pro"}
    second = await client.post(
        "/api/v1/billing/checkout-session", headers=headers, json={"plan": "premium"}
    )
    assert second.json() == {"url": "https://checkout.stripe.test/premium"}

    # The customer is created once and reused; the right price is sent each time.
    assert len(fakes.billing.customers) == 1
    assert fakes.billing.customers[0]["email"] == "upgrading-electrical@example.com"
    assert [checkout["price_id"] for checkout in fakes.billing.checkouts] == [PRO, PREMIUM]
    assert (await _reload(db, installer)).stripe_customer_id == "cus_test_1"
    # Starting a checkout never grants the plan: only the webhook does.
    assert installer.plan is Plan.FREE


async def test_portal_needs_a_billing_account_and_checkout_refuses_a_second_subscription(
    client: httpx.AsyncClient, db: AsyncSession
):
    installer = await create_installer(db, "Subscribed Electrical", plan=Plan.FREE)
    headers = auth_headers(installer.user)

    no_account = await client.post("/api/v1/billing/portal-session", headers=headers)
    assert (no_account.status_code, no_account.json()["error"]["code"]) == (
        409,
        "no_billing_account",
    )

    installer.stripe_customer_id = "cus_live"
    installer.subscription_status = SubscriptionStatus.ACTIVE
    installer.plan = Plan.PRO
    db.add(installer)
    await db.commit()

    portal = await client.post("/api/v1/billing/portal-session", headers=headers)
    assert portal.json() == {"url": "https://portal.stripe.test/cus_live"}
    again = await client.post(
        "/api/v1/billing/checkout-session", headers=headers, json={"plan": "premium"}
    )
    assert (again.status_code, again.json()["error"]["code"]) == (409, "already_subscribed")


async def test_webhook_rejects_unsigned_and_tampered_payloads(
    client: httpx.AsyncClient, db: AsyncSession
):
    installer = await create_installer(db, "Target Electrical", plan=Plan.FREE)
    body, headers = signed_stripe_event(
        "customer.subscription.created",
        subscription_object(installer, status="active", price_id=PREMIUM),
    )

    unsigned = await client.post(
        WEBHOOK, content=body, headers={"Content-Type": "application/json"}
    )
    tampered = await client.post(
        WEBHOOK, content=body.replace(b"active", b"ACTIVE"), headers=headers
    )
    forged = await client.post(
        WEBHOOK, content=body, headers={**headers, "Stripe-Signature": "t=1,v1=deadbeef"}
    )
    for response in (unsigned, tampered, forged):
        assert (response.status_code, response.json()["error"]["code"]) == (400, "invalid_webhook")

    assert (await _reload(db, installer)).plan is Plan.FREE
    assert await db.scalar(select(func.count()).select_from(StripeEvent)) == 0


async def test_subscription_events_grant_change_and_remove_the_plan(
    client: httpx.AsyncClient, db: AsyncSession
):
    installer = await create_installer(db, "Lifecycle Electrical", plan=Plan.FREE)

    async def deliver(event_type: str, **subscription) -> None:
        body, headers = signed_stripe_event(
            event_type, subscription_object(installer, **subscription)
        )
        response = await client.post(WEBHOOK, content=body, headers=headers)
        assert (response.status_code, response.json()) == (200, {"received": True})
        await _reload(db, installer)

    await deliver("customer.subscription.created", status="active", price_id=PRO)
    assert (installer.plan, installer.subscription_status) == (Plan.PRO, SubscriptionStatus.ACTIVE)
    assert installer.stripe_subscription_id == "sub_test_1"
    assert installer.current_period_end is not None

    await deliver("customer.subscription.updated", status="active", price_id=PREMIUM)
    assert installer.plan is Plan.PREMIUM

    # Not paid up: the subscription is kept, but the paid plan's benefits are withdrawn.
    await deliver("customer.subscription.updated", status="past_due", price_id=PREMIUM)
    assert (installer.plan, installer.subscription_status) == (
        Plan.FREE,
        SubscriptionStatus.PAST_DUE,
    )

    await deliver("customer.subscription.updated", status="active", price_id=PREMIUM)
    assert installer.plan is Plan.PREMIUM

    await deliver("customer.subscription.deleted", status="canceled", price_id=PREMIUM)
    assert (installer.plan, installer.subscription_status, installer.stripe_subscription_id) == (
        Plan.FREE,
        SubscriptionStatus.CANCELED,
        None,
    )

    # An unknown price never grants a paid plan.
    await deliver("customer.subscription.created", status="active", price_id="price_unknown")
    assert installer.plan is Plan.FREE


async def test_webhook_events_are_applied_exactly_once(client: httpx.AsyncClient, db: AsyncSession):
    installer = await create_installer(db, "Idempotent Electrical", plan=Plan.FREE)
    body, headers = signed_stripe_event(
        "customer.subscription.created",
        subscription_object(installer, status="active", price_id=PRO),
        event_id="evt_delivered_twice",
    )
    assert (await client.post(WEBHOOK, content=body, headers=headers)).status_code == 200

    # Something else changes the plan; a redelivery of the old event must not undo it.
    (await _reload(db, installer)).plan = Plan.PREMIUM
    db.add(installer)
    await db.commit()
    assert (await client.post(WEBHOOK, content=body, headers=headers)).status_code == 200

    assert (await _reload(db, installer)).plan is Plan.PREMIUM
    assert await db.scalar(select(func.count()).select_from(StripeEvent)) == 1


async def test_checkout_completed_fetches_the_subscription_and_grants_the_plan(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_installer(db, "Checkout Electrical", plan=Plan.FREE)
    fakes.billing.subscriptions["sub_checkout"] = subscription_object(
        installer, status="active", price_id=PRO, subscription_id="sub_checkout"
    )
    body, headers = signed_stripe_event(
        "checkout.session.completed",
        {
            "id": "cs_test_1",
            "object": "checkout.session",
            "client_reference_id": str(installer.id),
            "customer": "cus_from_checkout",
            "subscription": "sub_checkout",
        },
    )
    assert (await client.post(WEBHOOK, content=body, headers=headers)).status_code == 200

    await _reload(db, installer)
    assert (installer.plan, installer.stripe_customer_id, installer.stripe_subscription_id) == (
        Plan.PRO,
        "cus_from_checkout",
        "sub_checkout",
    )


async def test_failed_payment_withdraws_the_paid_plan(client: httpx.AsyncClient, db: AsyncSession):
    installer = await create_installer(db, "Late Payer Electrical", plan=Plan.PRO)
    installer.stripe_customer_id = "cus_late"
    installer.subscription_status = SubscriptionStatus.ACTIVE
    db.add(installer)
    await db.commit()

    body, headers = signed_stripe_event(
        "invoice.payment_failed", {"id": "in_test_1", "object": "invoice", "customer": "cus_late"}
    )
    assert (await client.post(WEBHOOK, content=body, headers=headers)).status_code == 200
    await _reload(db, installer)
    assert (installer.plan, installer.subscription_status) == (
        Plan.FREE,
        SubscriptionStatus.PAST_DUE,
    )

    ignored_body, ignored_headers = signed_stripe_event(
        "payment_intent.created", {"id": "pi_test_1", "object": "payment_intent"}
    )
    ignored = await client.post(WEBHOOK, content=ignored_body, headers=ignored_headers)
    assert ignored.status_code == 200
