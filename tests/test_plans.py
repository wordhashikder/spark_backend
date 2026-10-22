"""Membership plans: the public catalogue and the Dashboard's plan manager (CRUD)."""

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import Role, StaffRole
from app.core.plans import capabilities_for, lead_receiving_plan_keys, registry
from app.models import Installer, PlanPrice
from tests.helpers import (
    Fakes,
    Plan,
    auth_headers,
    create_installer,
    create_user,
    link_stripe_prices,
)

ADMIN = "/api/v1/admin"
PLANS = f"{ADMIN}/plans"
PUBLIC = "/api/v1/plans"


async def _owner(db: AsyncSession) -> dict[str, str]:
    return auth_headers(await create_user(db, role=Role.ADMIN, staff_role=StaffRole.OWNER))


def _plan(**overrides) -> dict:
    return {
        "key": "business",
        "name": "Business",
        "tagline": "For growing teams",
        "features": ["Everything in Premium", "Priority support"],
        "price_pence": 7900,
        "sort_rank": 3,
        "receives_leads": True,
        "accepts_direct_quotes": True,
        "full_public_profile": True,
        "max_gallery_photos": 40,
    } | overrides


# ---- Public catalogue ---------------------------------------------------------------------


async def test_public_plans_are_the_seeded_catalogue_in_order(client: httpx.AsyncClient):
    response = await client.get(PUBLIC)
    assert response.status_code == 200
    assert "max-age" in response.headers["cache-control"]
    plans = response.json()
    assert [(p["key"], p["name"], p["price_pence"]) for p in plans] == [
        ("free", "Free", None),
        ("pro", "Pro", 2900),
        ("premium", "Premium", 4900),
    ]
    pro = plans[1]
    assert pro["is_popular"] is True
    assert pro["currency"] == "gbp"
    assert len(pro["features"]) > 1
    # Nothing internal leaks into the public catalogue.
    assert "stripe_price_id" not in pro
    assert "receives_leads" not in pro


async def test_public_plans_hide_archived_and_unpriced_plans(
    client: httpx.AsyncClient, db: AsyncSession
):
    owner = await _owner(db)
    await client.post(PLANS, headers=owner, json=_plan(key="hidden", price_pence=None))
    await client.post(PLANS, headers=owner, json=_plan(key="visible", price_pence=1500))
    keys = [p["key"] for p in (await client.get(PUBLIC)).json()]
    assert "visible" in keys
    assert "hidden" not in keys

    await client.patch(f"{PLANS}/pro", headers=owner, json={"is_active": False})
    keys = [p["key"] for p in (await client.get(PUBLIC)).json()]
    assert "pro" not in keys
    assert "free" in keys


# ---- Create -------------------------------------------------------------------------------


async def test_creating_a_plan_makes_it_public_and_creates_it_in_stripe(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    owner = await _owner(db)
    created = await client.post(PLANS, headers=owner, json=_plan())
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["key"], body["price_pence"], body["currency"]) == ("business", 7900, "gbp")
    assert body["stripe_synced"] is True
    assert body["stripe_product_id"] == "prod_business"
    assert body["stripe_price_id"] in fakes.billing.prices
    assert fakes.billing.prices[body["stripe_price_id"]]["amount_pence"] == 7900
    assert (body["installers"], body["subscriptions"]) == (0, 0)
    assert "plans" in fakes.revalidator.tags

    public = {p["key"]: p for p in (await client.get(PUBLIC)).json()}
    assert public["business"]["price_pence"] == 7900
    assert list(public) == ["free", "pro", "premium", "business"]
    assert registry.get("business") is not None

    listing = await client.get(PLANS, headers=owner)
    assert [p["key"] for p in listing.json()] == ["free", "pro", "premium", "business"]


async def test_plan_validation(client: httpx.AsyncClient, db: AsyncSession):
    owner = await _owner(db)
    duplicate = await client.post(PLANS, headers=owner, json=_plan(key="pro"))
    assert (duplicate.status_code, duplicate.json()["error"]["fields"]) == (
        422,
        {"key": "A plan with this key already exists."},
    )
    for bad_key in ("Pro", "1pro", "pro plan", "a", "-x", "x" * 41):
        refused = await client.post(PLANS, headers=owner, json=_plan(key=bad_key))
        assert refused.status_code == 422, bad_key
    for bad_price in (0, 99, 1_000_001, -5):
        refused = await client.post(PLANS, headers=owner, json=_plan(price_pence=bad_price))
        assert refused.status_code == 422, bad_price
    no_name = await client.post(PLANS, headers=owner, json=_plan(name=" "))
    assert no_name.status_code == 422
    too_many = await client.post(
        PLANS, headers=owner, json=_plan(features=[f"Feature {i}" for i in range(13)])
    )
    assert too_many.status_code == 422
    assert (await client.get(PLANS, headers=owner)).json()[-1]["key"] == "premium"


async def test_only_one_plan_is_marked_popular(client: httpx.AsyncClient, db: AsyncSession):
    owner = await _owner(db)
    await client.post(PLANS, headers=owner, json=_plan(is_popular=True))
    plans = {p["key"]: p for p in (await client.get(PLANS, headers=owner)).json()}
    assert [key for key, plan in plans.items() if plan["is_popular"]] == ["business"]


async def test_a_plan_without_a_price_is_saved_but_cannot_be_bought(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    owner = await _owner(db)
    created = await client.post(
        PLANS, headers=owner, json=_plan(key="invite-only", price_pence=None)
    )
    assert created.status_code == 201
    assert (created.json()["price_pence"], created.json()["stripe_synced"]) == (None, True)
    assert fakes.billing.products == {}

    installer = await create_installer(db, "Wants Invite Only", plan=Plan.FREE)
    attempt = await client.post(
        "/api/v1/billing/checkout-session",
        headers=auth_headers(installer.user),
        json={"plan": "invite-only"},
    )
    assert attempt.status_code == 422
    assert attempt.json()["error"]["fields"] == {"plan": "This plan cannot be bought."}


# ---- Update -------------------------------------------------------------------------------


async def test_editing_a_plan_applies_immediately(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    owner = await _owner(db)
    assert capabilities_for("pro").max_gallery_photos == 12

    response = await client.patch(
        f"{PLANS}/pro",
        headers=owner,
        json={
            "name": "Pro+",
            "features": ["One", "Two"],
            "max_gallery_photos": 30,
            "tagline": None,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["name"], body["features"], body["max_gallery_photos"]) == (
        "Pro+",
        ["One", "Two"],
        30,
    )
    assert body["tagline"] is None
    # Fields left out are untouched.
    assert (body["price_pence"], body["receives_leads"], body["is_popular"]) == (2900, True, True)
    assert capabilities_for("pro").max_gallery_photos == 30
    assert {"plans", "installers", "locations"} <= set(fakes.revalidator.tags)

    public = {p["key"]: p for p in (await client.get(PUBLIC)).json()}
    assert public["pro"]["name"] == "Pro+"

    # Clearing the service limit shows every service publicly.
    cleared = await client.patch(
        f"{PLANS}/free", headers=owner, json={"public_service_limit": None}
    )
    assert cleared.json()["public_service_limit"] is None
    assert capabilities_for("free").public_service_limit is None


async def test_capability_flags_drive_which_plans_receive_leads(
    client: httpx.AsyncClient, db: AsyncSession
):
    owner = await _owner(db)
    assert set(lead_receiving_plan_keys()) == {"pro", "premium"}
    await client.patch(f"{PLANS}/free", headers=owner, json={"receives_leads": True})
    await client.patch(f"{PLANS}/pro", headers=owner, json={"receives_leads": False})
    assert set(lead_receiving_plan_keys()) == {"free", "premium"}


async def test_changing_the_price_retires_the_old_one_and_keeps_history(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    owner = await _owner(db)
    prices = await link_stripe_prices(db)

    response = await client.patch(f"{PLANS}/pro", headers=owner, json={"price_pence": 3500})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["price_pence"] == 3500
    assert [(p["amount_pence"], p["is_active"]) for p in body["prices"]] == [
        (3500, True),
        (2900, False),
    ]
    # The old price stops being offered in Stripe but its subscribers keep paying it.
    assert fakes.billing.archived_prices == [prices["pro"]]
    assert body["stripe_price_id"] != prices["pro"]
    assert fakes.billing.prices[body["stripe_price_id"]]["amount_pence"] == 3500

    public = {p["key"]: p for p in (await client.get(PUBLIC)).json()}
    assert public["pro"]["price_pence"] == 3500

    # Saving the same price again changes nothing.
    again = await client.patch(f"{PLANS}/pro", headers=owner, json={"price_pence": 3500})
    assert len(again.json()["prices"]) == 2
    assert fakes.billing.archived_prices == [prices["pro"]]


async def test_removing_the_price_withdraws_the_plan_from_sale(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    owner = await _owner(db)
    prices = await link_stripe_prices(db)
    response = await client.patch(f"{PLANS}/premium", headers=owner, json={"price_pence": None})
    assert response.status_code == 200, response.text
    assert response.json()["price_pence"] is None
    assert fakes.billing.archived_prices == [prices["premium"]]
    assert "premium" not in [p["key"] for p in (await client.get(PUBLIC)).json()]


async def test_the_default_plan_is_protected(client: httpx.AsyncClient, db: AsyncSession):
    owner = await _owner(db)
    archived = await client.patch(f"{PLANS}/free", headers=owner, json={"is_active": False})
    assert archived.status_code == 422
    assert archived.json()["error"]["fields"] == {
        "is_active": "The default plan cannot be archived."
    }
    priced = await client.patch(f"{PLANS}/free", headers=owner, json={"price_pence": 500})
    assert priced.status_code == 422
    assert priced.json()["error"]["fields"] == {"price_pence": "The default plan is always free."}
    deleted = await client.delete(f"{PLANS}/free", headers=owner)
    assert (deleted.status_code, deleted.json()["error"]["code"]) == (409, "default_plan")


async def test_update_validation_and_unknown_plans(client: httpx.AsyncClient, db: AsyncSession):
    owner = await _owner(db)
    missing = await client.patch(f"{PLANS}/nope", headers=owner, json={"name": "X"})
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "plan_not_found")
    for body in ({"name": None}, {"price_pence": 50}, {"key": "other"}, {"features": None}):
        refused = await client.patch(f"{PLANS}/pro", headers=owner, json=body)
        assert refused.status_code == 422, body


# ---- Delete -------------------------------------------------------------------------------


async def test_a_plan_in_use_cannot_be_deleted_but_an_unused_one_can(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    owner = await _owner(db)
    await create_installer(db, "On Pro", plan=Plan.PRO)
    blocked = await client.delete(f"{PLANS}/pro", headers=owner)
    assert (blocked.status_code, blocked.json()["error"]["code"]) == (409, "plan_in_use")

    # A booked downgrade or an admin-side request counts as being on the plan too.
    other = await create_installer(db, "Heading To Premium", plan=Plan.PRO)
    other.pending_plan = Plan.PREMIUM
    db.add(other)
    await db.commit()
    assert (await client.delete(f"{PLANS}/premium", headers=owner)).status_code == 409

    await client.post(PLANS, headers=owner, json=_plan(key="short-lived", price_pence=1000))
    gone = await client.delete(f"{PLANS}/short-lived", headers=owner)
    assert gone.status_code == 204
    assert fakes.billing.archived_products == ["prod_short-lived"]
    assert len(fakes.billing.archived_prices) == 1
    assert registry.get("short-lived") is None
    assert "short-lived" not in [p["key"] for p in (await client.get(PLANS, headers=owner)).json()]
    assert (await client.delete(f"{PLANS}/short-lived", headers=owner)).status_code == 404


async def test_archiving_keeps_current_subscribers_on_their_plan(
    client: httpx.AsyncClient, db: AsyncSession
):
    owner = await _owner(db)
    installer = await create_installer(db, "Stays On Pro", plan=Plan.PRO)
    await client.patch(f"{PLANS}/pro", headers=owner, json={"is_active": False})
    await db.refresh(installer)
    assert installer.plan == Plan.PRO
    assert capabilities_for("pro").receives_leads is True
    listing = {p["key"]: p for p in (await client.get(PLANS, headers=owner)).json()}
    assert listing["pro"]["is_active"] is False
    assert listing["pro"]["installers"] == 1


# ---- Stripe availability ------------------------------------------------------------------


async def test_a_stripe_outage_saves_nothing(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    owner = await _owner(db)
    fakes.billing.fail_catalogue = True
    failed = await client.post(PLANS, headers=owner, json=_plan())
    assert (failed.status_code, failed.json()["error"]["code"]) == (503, "billing_unavailable")
    assert "business" not in [p["key"] for p in (await client.get(PLANS, headers=owner)).json()]
    assert registry.get("business") is None

    fakes.billing.fail_catalogue = False
    assert (await client.post(PLANS, headers=owner, json=_plan())).status_code == 201


async def test_without_stripe_plans_are_saved_and_synced_later(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession, monkeypatch
):
    owner = await _owner(db)
    monkeypatch.setattr(get_settings(), "stripe_secret_key", None)
    created = await client.post(PLANS, headers=owner, json=_plan())
    assert created.status_code == 201, created.text
    assert (created.json()["stripe_synced"], created.json()["stripe_price_id"]) == (False, None)
    assert fakes.billing.prices == {}
    listing = {p["key"]: p for p in (await client.get(PLANS, headers=owner)).json()}
    assert listing["pro"]["stripe_synced"] is False  # seeded plans have no Stripe price yet

    monkeypatch.undo()
    synced = await client.post(f"{PLANS}/sync-stripe", headers=owner)
    assert synced.status_code == 200, synced.text
    assert synced.json()["plans_updated"] == 3
    listing = {p["key"]: p for p in (await client.get(PLANS, headers=owner)).json()}
    assert all(p["stripe_synced"] for p in listing.values())
    assert listing["business"]["stripe_product_id"] == "prod_business"
    assert fakes.billing.prices[listing["pro"]["stripe_price_id"]]["amount_pence"] == 2900

    # Nothing left to do the second time.
    assert (await client.post(f"{PLANS}/sync-stripe", headers=owner)).json()["plans_updated"] == 0


# ---- Access and assignment ----------------------------------------------------------------


async def test_only_staff_with_the_billing_module_manage_plans(
    client: httpx.AsyncClient, db: AsyncSession
):
    manager = auth_headers(await create_user(db, role=Role.ADMIN, staff_role=StaffRole.MANAGER))
    denied = await client.get(PLANS, headers=manager)
    assert (denied.status_code, denied.json()["error"]["code"]) == (403, "module_forbidden")
    assert (await client.post(PLANS, headers=manager, json=_plan())).status_code == 403
    assert (await client.get(f"{ADMIN}/payments", headers=manager)).status_code == 403

    installer = await create_installer(db, "Not Staff")
    assert (await client.get(PLANS, headers=auth_headers(installer.user))).status_code == 403
    assert (await client.get(PLANS)).status_code == 401

    me = (await client.get("/api/v1/auth/me", headers=await _owner(db))).json()
    assert "billing" in me["permissions"]


async def test_the_team_can_only_assign_plans_that_exist(
    client: httpx.AsyncClient, db: AsyncSession
):
    owner = await _owner(db)
    installer = await create_installer(db, "Reassigned", plan=Plan.FREE)

    ok = await client.patch(
        f"{ADMIN}/installers/{installer.id}", headers=owner, json={"plan": "premium"}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["plan"] == "premium"
    assert ok.json()["plan_name"] == "Premium"

    unknown = await client.patch(
        f"{ADMIN}/installers/{installer.id}", headers=owner, json={"plan": "gold"}
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["fields"] == {"plan": "This plan does not exist."}
    refreshed = await db.scalar(select(Installer.plan).where(Installer.id == installer.id))
    assert refreshed == "premium"

    by_plan = await client.get(f"{ADMIN}/installers", headers=owner, params={"plan": "premium"})
    assert [i["id"] for i in by_plan.json()["items"]] == [str(installer.id)]


async def test_price_rows_are_unique_per_active_interval(db: AsyncSession):
    await link_stripe_prices(db)
    active = await db.scalars(
        select(PlanPrice).where(PlanPrice.plan_key == "pro", PlanPrice.is_active)
    )
    assert len(list(active)) == 1


async def test_installers_screen_lists_every_plan_for_managers_too(
    client: httpx.AsyncClient, db: AsyncSession
):
    owner = await _owner(db)
    await client.patch(f"{PLANS}/pro", headers=owner, json={"is_active": False})
    manager = auth_headers(await create_user(db, role=Role.ADMIN, staff_role=StaffRole.MANAGER))
    options = await client.get(f"{ADMIN}/installers/plan-options", headers=manager)
    assert options.status_code == 200, options.text
    assert [(o["key"], o["name"], o["is_active"]) for o in options.json()] == [
        ("free", "Free", True),
        ("pro", "Pro", False),
        ("premium", "Premium", True),
    ]


async def test_the_installers_own_profile_reports_what_their_plan_allows(
    client: httpx.AsyncClient, db: AsyncSession
):
    owner = await _owner(db)
    installer = await create_installer(db, "Sees Limits", plan=Plan.PRO)
    headers = auth_headers(installer.user)

    me = (await client.get("/api/v1/installers/me", headers=headers)).json()
    assert (me["plan_name"], me["max_gallery_photos"], me["public_service_limit"]) == (
        "Pro",
        12,
        None,
    )
    await client.patch(f"{PLANS}/pro", headers=owner, json={"max_gallery_photos": 3})
    me = (await client.get("/api/v1/installers/me", headers=headers)).json()
    assert me["max_gallery_photos"] == 3
