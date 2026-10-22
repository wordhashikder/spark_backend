"""The payment pipeline: checkout, plan changes, cancellation, history and Stripe webhooks."""

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import SubscriptionStatus
from app.models import BillingActivity, BillingInvoice, Installer, PlanPrice, StripeEvent
from tests.helpers import (
    Fakes,
    Plan,
    auth_headers,
    create_installer,
    create_subscriber,
    invoice_object,
    link_stripe_prices,
    signed_stripe_event,
    subscription_object,
)

BILLING = "/api/v1/billing"
WEBHOOK = f"{BILLING}/webhook"
PRO, PREMIUM = "price_pro_test", "price_premium_test"


async def _reload(db: AsyncSession, installer: Installer) -> Installer:
    await db.refresh(installer)
    return installer


async def _deliver(
    client: httpx.AsyncClient, event_type: str, data: dict, event_id: str | None = None
) -> httpx.Response:
    body, headers = signed_stripe_event(event_type, data, event_id=event_id)
    return await client.post(WEBHOOK, content=body, headers=headers)


async def _activity(db: AsyncSession, installer: Installer) -> list[str]:
    rows = await db.scalars(
        select(BillingActivity.kind)
        .where(BillingActivity.installer_id == installer.id)
        .order_by(BillingActivity.created_at, BillingActivity.id)
    )
    return list(rows)


# ---- Checkout ---------------------------------------------------------------------------


async def test_checkout_creates_one_customer_and_uses_the_plans_stripe_price(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_installer(db, "Upgrading Electrical", plan=Plan.FREE)
    headers = auth_headers(installer.user)

    assert (
        await client.post(f"{BILLING}/checkout-session", json={"plan": "pro"})
    ).status_code == 401
    # Neither the free plan nor an unknown plan can be bought.
    for plan in ("free", "gold"):
        refused = await client.post(
            f"{BILLING}/checkout-session", headers=headers, json={"plan": plan}
        )
        assert refused.status_code in (404, 422), (plan, refused.text)

    first = await client.post(f"{BILLING}/checkout-session", headers=headers, json={"plan": "pro"})
    assert first.status_code == 200, first.text
    assert first.json() == {"url": "https://checkout.stripe.test/pro"}
    second = await client.post(
        f"{BILLING}/checkout-session", headers=headers, json={"plan": "premium"}
    )
    assert second.json() == {"url": "https://checkout.stripe.test/premium"}

    # The customer is created once and reused. The paid plans had no Stripe price yet, so
    # each was created in Stripe from the database price the first time it was bought.
    assert len(fakes.billing.customers) == 1
    assert fakes.billing.customers[0]["email"] == "upgrading-electrical@example.com"
    assert [price["amount_pence"] for price in fakes.billing.prices.values()] == [2900, 4900]
    assert [c["plan_key"] for c in fakes.billing.checkouts] == ["pro", "premium"]
    assert (await _reload(db, installer)).stripe_customer_id == "cus_test_1"
    # Starting a checkout never grants the plan: only Stripe's confirmation does.
    assert installer.plan == Plan.FREE


async def test_checkout_return_urls_point_at_the_dashboard(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_installer(db, "Returning Electrical", plan=Plan.FREE)
    await client.post(
        f"{BILLING}/checkout-session", headers=auth_headers(installer.user), json={"plan": "pro"}
    )
    dashboard = get_settings().dashboard_url.rstrip("/")
    checkout = fakes.billing.checkouts[0]
    assert (
        checkout["success_url"] == f"{dashboard}/billing/success?session_id={{CHECKOUT_SESSION_ID}}"
    )
    assert checkout["cancel_url"] == f"{dashboard}/billing/cancelled"


async def test_checkout_refuses_a_second_subscription_and_an_unavailable_plan(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    subscriber = await create_subscriber(db, fakes, plan=Plan.PRO)
    again = await client.post(
        f"{BILLING}/checkout-session",
        headers=auth_headers(subscriber.user),
        json={"plan": "premium"},
    )
    assert (again.status_code, again.json()["error"]["code"]) == (409, "already_subscribed")

    other = await create_installer(db, "Archived Plan Electrical", plan=Plan.FREE)
    owner = await create_installer(db, "Owner", plan=Plan.FREE)
    del owner
    from app.models import Plan as PlanRow

    (await db.get(PlanRow, "premium")).is_active = False
    await db.commit()
    refused = await client.post(
        f"{BILLING}/checkout-session",
        headers=auth_headers(other.user),
        json={"plan": "premium"},
    )
    assert refused.status_code == 422
    assert refused.json()["error"]["fields"] == {"plan": "This plan cannot be bought."}


async def test_billing_reports_503_when_stripe_is_not_configured(
    client: httpx.AsyncClient, db: AsyncSession, monkeypatch
):
    installer = await create_installer(db, "Offline Electrical", plan=Plan.FREE)
    headers = auth_headers(installer.user)
    monkeypatch.setattr(get_settings(), "stripe_secret_key", None)

    checkout = await client.post(
        f"{BILLING}/checkout-session", headers=headers, json={"plan": "pro"}
    )
    assert (checkout.status_code, checkout.json()["error"]["code"]) == (
        503,
        "service_not_configured",
    )
    summary = await client.get(f"{BILLING}/summary", headers=headers)
    assert summary.json()["billing_enabled"] is False


async def test_checkout_status_grants_the_plan_when_the_payment_went_through(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    prices = await link_stripe_prices(db)
    installer = await create_installer(db, "Checkout Electrical", plan=Plan.FREE)
    headers = auth_headers(installer.user)
    subscription = subscription_object(
        installer,
        status="active",
        price_id=prices["pro"],
        subscription_id="sub_checkout",
        latest_invoice=invoice_object(installer, price_id=prices["pro"]),
    )
    fakes.billing.checkout_sessions["cs_test_ok"] = {
        "id": "cs_test_ok",
        "client_reference_id": str(installer.id),
        "customer": "cus_from_checkout",
        "status": "complete",
        "payment_status": "paid",
        "subscription": subscription,
    }

    done = await client.get(f"{BILLING}/checkout-status?session_id=cs_test_ok", headers=headers)
    assert done.status_code == 200, done.text
    assert done.json() == {"state": "paid", "plan": {"key": "pro", "name": "Pro"}}

    await _reload(db, installer)
    assert (installer.plan, installer.stripe_customer_id, installer.stripe_subscription_id) == (
        Plan.PRO,
        "cus_from_checkout",
        "sub_checkout",
    )
    assert installer.subscription_status is SubscriptionStatus.ACTIVE
    assert await _activity(db, installer) == ["subscribed"]
    invoice = await db.get(BillingInvoice, "in_test_1")
    assert (invoice.status, invoice.amount_paid_pence, invoice.plan_name) == ("paid", 2900, "Pro")

    # Asking again changes nothing and records nothing twice.
    again = await client.get(f"{BILLING}/checkout-status?session_id=cs_test_ok", headers=headers)
    assert again.json()["state"] == "paid"
    assert await _activity(db, installer) == ["subscribed"]
    assert await db.scalar(select(func.count()).select_from(BillingInvoice)) == 1


async def test_checkout_status_other_states_and_ownership(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_installer(db, "Waiting Electrical", plan=Plan.FREE)
    stranger = await create_installer(db, "Stranger Electrical", plan=Plan.FREE)
    headers = auth_headers(installer.user)
    base = {"client_reference_id": str(installer.id), "customer": "cus_x", "subscription": None}
    for session_id, extra, state in (
        ("cs_test_open", {"status": "open", "payment_status": "unpaid"}, "open"),
        ("cs_test_expired", {"status": "expired", "payment_status": "unpaid"}, "expired"),
        ("cs_test_settling", {"status": "complete", "payment_status": "unpaid"}, "processing"),
    ):
        fakes.billing.checkout_sessions[session_id] = base | extra | {"id": session_id}
        response = await client.get(
            f"{BILLING}/checkout-status?session_id={session_id}", headers=headers
        )
        assert response.json() == {"state": state, "plan": None}, session_id

    # Someone else's checkout, or a malformed id, is never revealed.
    foreign = await client.get(
        f"{BILLING}/checkout-status?session_id=cs_test_open", headers=auth_headers(stranger.user)
    )
    assert (foreign.status_code, foreign.json()["error"]["code"]) == (404, "checkout_not_found")
    malformed = await client.get(f"{BILLING}/checkout-status?session_id=nope", headers=headers)
    assert malformed.status_code == 422
    assert (await _reload(db, installer)).plan == Plan.FREE


async def test_portal_needs_a_billing_account_and_returns_to_the_billing_page(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_installer(db, "Portal Electrical", plan=Plan.FREE)
    headers = auth_headers(installer.user)
    no_account = await client.post(f"{BILLING}/portal-session", headers=headers)
    assert (no_account.status_code, no_account.json()["error"]["code"]) == (
        409,
        "no_billing_account",
    )

    subscriber = await create_subscriber(db, fakes, name="Portal Subscriber")
    portal = await client.post(f"{BILLING}/portal-session", headers=auth_headers(subscriber.user))
    assert portal.json() == {"url": f"https://portal.stripe.test/{subscriber.stripe_customer_id}"}
    assert fakes.billing.portal_return_url.endswith("/billing")


# ---- Upgrade, downgrade, cancel, resume ----------------------------------------------------


async def test_summary_lists_what_each_plan_would_mean(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    free = await create_installer(db, "Free Summary", plan=Plan.FREE)
    summary = (await client.get(f"{BILLING}/summary", headers=auth_headers(free.user))).json()
    assert summary["plan"] == {"key": "free", "name": "Free"}
    assert (summary["has_subscription"], summary["auto_renew"]) == (False, False)
    assert [(o["key"], o["action"], o["price_pence"]) for o in summary["options"]] == [
        ("free", "current", None),
        ("pro", "subscribe", 2900),
        ("premium", "subscribe", 4900),
    ]

    pro = await create_subscriber(db, fakes, plan=Plan.PRO)
    summary = (await client.get(f"{BILLING}/summary", headers=auth_headers(pro.user))).json()
    assert summary["plan"]["key"] == "pro"
    assert (summary["has_subscription"], summary["auto_renew"]) == (True, True)
    assert summary["price_pence"] == 2900
    assert summary["current_period_end"].startswith("2027-01-15")
    assert [(o["key"], o["action"]) for o in summary["options"]] == [
        ("free", "cancel"),
        ("pro", "current"),
        ("premium", "upgrade"),
    ]


async def test_upgrade_takes_effect_now_and_records_the_charge(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_subscriber(db, fakes, plan=Plan.PRO)
    headers = auth_headers(installer.user)
    fakes.billing.subscriptions["sub_test_1"]["latest_invoice"] = invoice_object(
        installer,
        invoice_id="in_upgrade",
        amount=1500,
        price_id=PREMIUM,
        reason="subscription_update",
    )

    response = await client.post(
        f"{BILLING}/change-plan", headers=headers, json={"plan": "premium"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["plan"] == {"key": "premium", "name": "Premium"}
    assert response.json()["price_pence"] == 4900
    assert fakes.billing.price_changes == [{"subscription": "sub_test_1", "price": PREMIUM}]

    await _reload(db, installer)
    assert installer.plan == Plan.PREMIUM
    assert await _activity(db, installer) == ["upgraded"]
    invoice = await db.get(BillingInvoice, "in_upgrade")
    assert (invoice.billing_reason, invoice.amount_paid_pence) == ("subscription_update", 1500)


async def test_a_declined_upgrade_changes_nothing(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_subscriber(db, fakes, plan=Plan.PRO)
    fakes.billing.decline_price_change = True

    response = await client.post(
        f"{BILLING}/change-plan", headers=auth_headers(installer.user), json={"plan": "premium"}
    )
    assert (response.status_code, response.json()["error"]["code"]) == (402, "payment_declined")
    assert (await _reload(db, installer)).plan == Plan.PRO
    assert await _activity(db, installer) == []


async def test_downgrade_is_booked_for_the_end_of_the_period_and_can_be_dropped(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_subscriber(db, fakes, plan=Plan.PREMIUM)
    headers = auth_headers(installer.user)

    response = await client.post(f"{BILLING}/change-plan", headers=headers, json={"plan": "pro"})
    assert response.status_code == 200, response.text
    body = response.json()
    # They keep Premium until the period they paid for ends.
    assert body["plan"]["key"] == "premium"
    assert body["pending_change"]["plan"] == {"key": "pro", "name": "Pro"}
    assert body["pending_change"]["effective_at"].startswith("2027-01-15")
    assert fakes.billing.price_changes == []
    assert len(fakes.billing.schedules) == 1
    await _reload(db, installer)
    assert (installer.plan, installer.pending_plan) == (Plan.PREMIUM, Plan.PRO)
    assert installer.stripe_schedule_id == "sub_sched_1"

    # Changing their mind releases the schedule.
    dropped = await client.post(f"{BILLING}/cancel-change", headers=headers)
    assert dropped.status_code == 200
    assert dropped.json()["pending_change"] is None
    assert fakes.billing.released_schedules == ["sub_sched_1"]
    await _reload(db, installer)
    assert (installer.plan, installer.pending_plan, installer.stripe_schedule_id) == (
        Plan.PREMIUM,
        None,
        None,
    )
    assert await _activity(db, installer) == ["downgrade_scheduled", "downgrade_cancelled"]

    nothing = await client.post(f"{BILLING}/cancel-change", headers=headers)
    assert (nothing.status_code, nothing.json()["error"]["code"]) == (409, "nothing_to_change")


async def test_the_booked_downgrade_applies_when_stripe_renews_on_the_new_price(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_subscriber(db, fakes, plan=Plan.PREMIUM)
    await client.post(
        f"{BILLING}/change-plan", headers=auth_headers(installer.user), json={"plan": "pro"}
    )

    # The period ends: Stripe moves the subscription to the next phase and drops the schedule.
    subscription = fakes.billing.subscriptions["sub_test_1"]
    subscription["items"]["data"][0]["price"] = {"id": PRO}
    subscription["schedule"] = None
    response = await _deliver(client, "customer.subscription.updated", subscription)
    assert response.status_code == 200

    await _reload(db, installer)
    assert (installer.plan, installer.pending_plan, installer.stripe_schedule_id) == (
        Plan.PRO,
        None,
        None,
    )
    assert await _activity(db, installer) == ["downgrade_scheduled", "plan_changed"]


async def test_choosing_the_same_plan_or_a_plan_without_a_subscription_is_refused(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    subscriber = await create_subscriber(db, fakes, plan=Plan.PRO)
    same = await client.post(
        f"{BILLING}/change-plan", headers=auth_headers(subscriber.user), json={"plan": "pro"}
    )
    assert (same.status_code, same.json()["error"]["code"]) == (409, "same_plan")

    free = await create_installer(db, "No Subscription", plan=Plan.FREE)
    none = await client.post(
        f"{BILLING}/change-plan", headers=auth_headers(free.user), json={"plan": "pro"}
    )
    assert (none.status_code, none.json()["error"]["code"]) == (409, "no_subscription")

    unknown = await client.post(
        f"{BILLING}/change-plan", headers=auth_headers(subscriber.user), json={"plan": "gold"}
    )
    assert unknown.status_code == 404


async def test_cancelling_turns_auto_renewal_off_and_resuming_turns_it_on(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_subscriber(db, fakes, plan=Plan.PRO)
    headers = auth_headers(installer.user)

    cancelled = await client.post(f"{BILLING}/cancel", headers=headers)
    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()
    # Nothing is lost yet: the plan runs to the end of the paid period.
    assert (body["plan"]["key"], body["auto_renew"], body["cancel_at_period_end"]) == (
        "pro",
        False,
        True,
    )
    assert body["current_period_end"].startswith("2027-01-15")
    assert (await _reload(db, installer)).cancel_at_period_end is True
    assert fakes.billing.subscriptions["sub_test_1"]["cancel_at_period_end"] is True

    # Cancelling twice is harmless.
    assert (await client.post(f"{BILLING}/cancel", headers=headers)).status_code == 200

    resumed = await client.post(f"{BILLING}/resume", headers=headers)
    assert resumed.status_code == 200
    assert (resumed.json()["auto_renew"], resumed.json()["cancel_at_period_end"]) == (True, False)
    assert fakes.billing.subscriptions["sub_test_1"]["cancel_at_period_end"] is False
    assert await _activity(db, installer) == ["cancel_scheduled", "resumed"]

    nothing = await client.post(f"{BILLING}/resume", headers=headers)
    assert (nothing.status_code, nothing.json()["error"]["code"]) == (409, "nothing_to_change")


async def test_cancelling_replaces_a_booked_downgrade_and_choosing_free_means_cancel(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_subscriber(db, fakes, plan=Plan.PREMIUM)
    headers = auth_headers(installer.user)
    await client.post(f"{BILLING}/change-plan", headers=headers, json={"plan": "pro"})

    response = await client.post(f"{BILLING}/change-plan", headers=headers, json={"plan": "free"})
    assert response.status_code == 200, response.text
    assert response.json()["cancel_at_period_end"] is True
    assert response.json()["pending_change"] is None
    # A subscription on a schedule is changed through the schedule: it was released first.
    assert fakes.billing.released_schedules == ["sub_sched_1"]
    await _reload(db, installer)
    assert (installer.plan, installer.pending_plan, installer.cancel_at_period_end) == (
        Plan.PREMIUM,
        None,
        True,
    )


async def test_a_lower_plan_chosen_while_cancelling_keeps_the_subscription_going(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_subscriber(db, fakes, plan=Plan.PREMIUM, cancel_at_period_end=True)
    response = await client.post(
        f"{BILLING}/change-plan", headers=auth_headers(installer.user), json={"plan": "pro"}
    )
    assert response.status_code == 200, response.text
    assert fakes.billing.subscriptions["sub_test_1"]["cancel_at_period_end"] is False
    await _reload(db, installer)
    assert (installer.cancel_at_period_end, installer.pending_plan) == (False, Plan.PRO)


async def test_nothing_can_be_changed_while_a_payment_is_overdue(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_subscriber(db, fakes, plan=Plan.PRO)
    installer.subscription_status = SubscriptionStatus.PAST_DUE
    installer.plan = Plan.FREE
    db.add(installer)
    await db.commit()
    headers = auth_headers(installer.user)

    refused = await client.post(f"{BILLING}/change-plan", headers=headers, json={"plan": "premium"})
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "payment_overdue")
    summary = (await client.get(f"{BILLING}/summary", headers=headers)).json()
    assert (summary["payment_failed"], summary["options"]) == (True, [])
    # Leaving is still possible.
    assert (await client.post(f"{BILLING}/cancel", headers=headers)).status_code == 200


# ---- History ----------------------------------------------------------------------------


async def test_invoices_and_activity_are_listed_for_the_installer_only(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_subscriber(db, fakes, plan=Plan.PRO)
    other = await create_subscriber(db, fakes, name="Other Subscriber", subscription_id="sub_other")
    for number, (who, invoice_id) in enumerate(
        ((installer, "in_a"), (installer, "in_b"), (other, "in_other")), start=1
    ):
        paid = invoice_object(who, invoice_id=invoice_id, price_id=PRO)
        paid["created"] += number
        response = await _deliver(client, "invoice.paid", paid)
        assert response.status_code == 200, response.text

    listing = await client.get(f"{BILLING}/invoices", headers=auth_headers(installer.user))
    body = listing.json()
    assert (body["total"], [i["id"] for i in body["items"]]) == (2, ["in_b", "in_a"])
    first = body["items"][0]
    assert (first["status"], first["amount_paid_pence"], first["plan_name"]) == (
        "paid",
        2900,
        "Pro",
    )
    assert first["hosted_invoice_url"] == "https://invoice.stripe.test/i/1"

    page_two = await client.get(
        f"{BILLING}/invoices?page=2&page_size=1", headers=auth_headers(installer.user)
    )
    assert [i["id"] for i in page_two.json()["items"]] == ["in_a"]

    await client.post(f"{BILLING}/cancel", headers=auth_headers(installer.user))
    activity = await client.get(f"{BILLING}/activity", headers=auth_headers(installer.user))
    assert [a["kind"] for a in activity.json()] == ["cancel_scheduled"]

    assert (await client.get(f"{BILLING}/invoices")).status_code == 401


# ---- Webhooks ---------------------------------------------------------------------------


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

    assert (await _reload(db, installer)).plan == Plan.FREE
    assert await db.scalar(select(func.count()).select_from(StripeEvent)) == 0


async def test_webhook_without_a_signing_secret_is_refused(
    client: httpx.AsyncClient, db: AsyncSession, monkeypatch
):
    installer = await create_installer(db, "No Secret Electrical", plan=Plan.FREE)
    body, headers = signed_stripe_event(
        "customer.subscription.created",
        subscription_object(installer, status="active", price_id=PRO),
    )
    monkeypatch.setattr(get_settings(), "stripe_webhook_secret", None)
    response = await client.post(WEBHOOK, content=body, headers=headers)
    assert (response.status_code, response.json()["error"]["code"]) == (
        503,
        "service_not_configured",
    )


async def test_subscription_events_grant_change_and_remove_the_plan(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    await link_stripe_prices(db)
    installer = await create_installer(db, "Lifecycle Electrical", plan=Plan.FREE)

    async def deliver(event_type: str, **subscription) -> None:
        obj = subscription_object(installer, **subscription)
        fakes.billing.subscriptions[obj["id"]] = obj
        response = await _deliver(client, event_type, obj)
        assert (response.status_code, response.json()) == (200, {"received": True})
        await _reload(db, installer)

    await deliver("customer.subscription.created", status="active", price_id=PRO)
    assert (installer.plan, installer.subscription_status) == (Plan.PRO, SubscriptionStatus.ACTIVE)
    assert installer.stripe_subscription_id == "sub_test_1"
    assert installer.current_period_end is not None
    assert installer.plan_price_id is not None

    await deliver("customer.subscription.updated", status="active", price_id=PREMIUM)
    assert installer.plan == Plan.PREMIUM

    # Not paid up: the subscription is kept, but the paid plan's benefits are withdrawn.
    await deliver("customer.subscription.updated", status="past_due", price_id=PREMIUM)
    assert (installer.plan, installer.subscription_status) == (
        Plan.FREE,
        SubscriptionStatus.PAST_DUE,
    )

    await deliver("customer.subscription.updated", status="active", price_id=PREMIUM)
    assert installer.plan == Plan.PREMIUM

    await deliver("customer.subscription.deleted", status="canceled", price_id=PREMIUM)
    assert (installer.plan, installer.subscription_status, installer.stripe_subscription_id) == (
        Plan.FREE,
        SubscriptionStatus.CANCELED,
        None,
    )
    assert await _activity(db, installer) == [
        "subscribed",
        "plan_changed",
        "plan_changed",
        "plan_restored",
        "ended",
    ]

    # A price that is not in the catalogue never grants a paid plan.
    await deliver("customer.subscription.created", status="active", price_id="price_unknown")
    assert installer.plan == Plan.FREE


async def test_an_old_event_cannot_undo_what_stripe_now_says(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_subscriber(db, fakes, plan=Plan.PRO)
    # Stripe's current state: Pro. A late event still claims Premium.
    stale = subscription_object(installer, status="active", price_id=PREMIUM)
    response = await _deliver(client, "customer.subscription.updated", stale)
    assert response.status_code == 200
    assert (await _reload(db, installer)).plan == Plan.PRO


async def test_webhook_events_are_applied_exactly_once(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    await link_stripe_prices(db)
    installer = await create_installer(db, "Idempotent Electrical", plan=Plan.FREE)
    obj = subscription_object(installer, status="active", price_id=PRO)
    fakes.billing.subscriptions[obj["id"]] = obj
    body, headers = signed_stripe_event(
        "customer.subscription.created", obj, event_id="evt_delivered_twice"
    )
    assert (await client.post(WEBHOOK, content=body, headers=headers)).status_code == 200

    # Something else changes the plan; a redelivery of the old event must not undo it.
    (await _reload(db, installer)).plan = Plan.PREMIUM
    db.add(installer)
    await db.commit()
    assert (await client.post(WEBHOOK, content=body, headers=headers)).status_code == 200

    assert (await _reload(db, installer)).plan == Plan.PREMIUM
    assert await db.scalar(select(func.count()).select_from(StripeEvent)) == 1


async def test_checkout_completed_fetches_the_subscription_and_grants_the_plan(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    await link_stripe_prices(db)
    installer = await create_installer(db, "Checkout Webhook Electrical", plan=Plan.FREE)
    fakes.billing.subscriptions["sub_checkout"] = subscription_object(
        installer,
        status="active",
        price_id=PRO,
        subscription_id="sub_checkout",
        latest_invoice=invoice_object(installer, price_id=PRO),
    )
    response = await _deliver(
        client,
        "checkout.session.completed",
        {
            "id": "cs_test_1",
            "object": "checkout.session",
            "client_reference_id": str(installer.id),
            "customer": "cus_from_checkout",
            "subscription": "sub_checkout",
        },
    )
    assert response.status_code == 200

    await _reload(db, installer)
    assert (installer.plan, installer.stripe_customer_id, installer.stripe_subscription_id) == (
        Plan.PRO,
        "cus_from_checkout",
        "sub_checkout",
    )
    assert await db.get(BillingInvoice, "in_test_1") is not None


async def test_failed_payment_withdraws_the_paid_plan_and_tells_the_installer(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_subscriber(db, fakes, plan=Plan.PRO)
    owner_email = installer.user.email

    failed = invoice_object(
        installer, invoice_id="in_failed", status="open", reason="subscription_cycle"
    )
    response = await _deliver(client, "invoice.payment_failed", failed)
    assert response.status_code == 200
    await _reload(db, installer)
    assert (installer.plan, installer.subscription_status) == (
        Plan.FREE,
        SubscriptionStatus.PAST_DUE,
    )
    assert await _activity(db, installer) == ["payment_failed"]
    assert (await db.get(BillingInvoice, "in_failed")).status == "open"

    [email] = fakes.emails.of("payment_failed")
    assert email.to == owner_email
    assert email.context["plan_name"] == "Pro"
    assert email.context["billing_url"].endswith("/billing")

    # Paying the invoice later restores the plan, and a paid invoice is never reopened.
    fakes.billing.subscriptions["sub_test_1"]["status"] = "active"
    await _deliver(
        client, "customer.subscription.updated", fakes.billing.subscriptions["sub_test_1"]
    )
    assert (await _reload(db, installer)).plan == Plan.PRO
    await _deliver(client, "invoice.paid", invoice_object(installer, invoice_id="in_failed"))
    await _deliver(client, "invoice.payment_failed", failed)
    assert (await db.get(BillingInvoice, "in_failed")).status == "paid"

    ignored = await _deliver(
        client, "payment_intent.created", {"id": "pi_1", "object": "payment_intent"}
    )
    assert ignored.status_code == 200


async def test_schedule_events_track_a_downgrade_made_in_the_stripe_portal(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_subscriber(db, fakes, plan=Plan.PREMIUM)
    schedule = {
        "id": "sub_sched_portal",
        "object": "subscription_schedule",
        "customer": installer.stripe_customer_id,
        "subscription": "sub_test_1",
        "status": "active",
        "phases": [{"items": [{"price": PREMIUM}]}, {"items": [{"price": PRO}]}],
    }
    await _deliver(client, "subscription_schedule.created", schedule)
    await _reload(db, installer)
    assert (installer.pending_plan, installer.stripe_schedule_id) == (Plan.PRO, "sub_sched_portal")

    await _deliver(client, "subscription_schedule.released", schedule | {"status": "released"})
    await _reload(db, installer)
    assert (installer.pending_plan, installer.stripe_schedule_id) == (None, None)


async def test_prices_retired_by_the_team_still_identify_the_plan_of_old_subscribers(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_subscriber(db, fakes, plan=Plan.PRO)
    headers = auth_headers(installer.user)
    old = await db.scalar(select(PlanPrice).where(PlanPrice.stripe_price_id == PRO))
    old.is_active = False
    db.add(PlanPrice(plan_key="pro", amount_pence=3900, stripe_price_id="price_pro_new"))
    await db.commit()

    subscription = fakes.billing.subscriptions["sub_test_1"]
    await _deliver(client, "customer.subscription.updated", subscription)
    await _reload(db, installer)
    assert (installer.plan, installer.plan_price_id) == (Plan.PRO, old.id)

    summary = await client.get(f"{BILLING}/summary", headers=headers)
    # Still paying what they signed up at, not today's price.
    assert summary.json()["price_pence"] == 2900


async def test_the_website_can_ask_stripe_to_return_there(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_installer(db, "Website Electrical", plan=Plan.FREE)
    headers = auth_headers(installer.user)
    frontend = get_settings().frontend_url.rstrip("/")

    await client.post(
        f"{BILLING}/checkout-session", headers=headers, json={"plan": "pro", "return_to": "website"}
    )
    checkout = fakes.billing.checkouts[0]
    assert checkout["success_url"] == (
        f"{frontend}/installer/account?checkout=success&session_id={{CHECKOUT_SESSION_ID}}"
    )
    assert checkout["cancel_url"] == f"{frontend}/installer/account?checkout=cancelled"

    bad = await client.post(
        f"{BILLING}/checkout-session", headers=headers, json={"plan": "pro", "return_to": "evil"}
    )
    assert bad.status_code == 422

    await client.post(f"{BILLING}/portal-session", headers=headers, json={"return_to": "website"})
    assert fakes.billing.portal_return_url == f"{frontend}/installer/account"
    await client.post(f"{BILLING}/portal-session", headers=headers)
    assert fakes.billing.portal_return_url.endswith("/billing")
