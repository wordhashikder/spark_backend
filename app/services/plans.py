"""The plan catalogue: keeping workers in step with it, the Dashboard's CRUD, Stripe sync.

Each plan with a price has a Stripe product, and each price a Stripe price. They are created
and updated from here (never configured by hand) whenever Stripe is set up; without Stripe
the catalogue still works and the missing links are filled in later, at the next save, with
"Sync with Stripe", or on the first checkout.
"""

import asyncio
import logging
from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.exceptions import ConflictError, FieldValidationError, NotFoundError
from app.core.plans import PlanCapabilities, PlanEntry, registry
from app.models import Installer, Plan, PlanPrice
from app.schemas.plan import PlanCreate, PlanUpdate
from app.services.stripe_gateway import BillingGateway, call_stripe

logger = logging.getLogger(__name__)

_REFRESH_SECONDS = 30.0
INTERVAL = "month"
CURRENCY = "gbp"


class PlanInUseError(ConflictError):
    code = "plan_in_use"
    message = "Installers are still on this plan. Archive it instead of deleting it."


# ---- The in-memory registry -------------------------------------------------------------


def _active_price(plan: Plan) -> PlanPrice | None:
    return next(
        (price for price in plan.prices if price.is_active and price.interval == INTERVAL), None
    )


def to_entry(plan: Plan) -> PlanEntry:
    price = _active_price(plan)
    return PlanEntry(
        key=plan.key,
        name=plan.name,
        tagline=plan.tagline,
        features=tuple(plan.features),
        is_default=plan.is_default,
        is_active=plan.is_active,
        is_popular=plan.is_popular,
        capabilities=PlanCapabilities(
            receives_leads=plan.receives_leads,
            accepts_direct_quotes=plan.accepts_direct_quotes,
            full_public_profile=plan.full_public_profile,
            public_service_limit=plan.public_service_limit,
            sort_rank=plan.sort_rank,
            max_gallery_photos=plan.max_gallery_photos,
        ),
        price_pence=price.amount_pence if price else None,
        currency=price.currency if price else CURRENCY,
    )


async def load_registry(session: AsyncSession) -> None:
    plans = await session.scalars(select(Plan).options(selectinload(Plan.prices)))
    registry.replace(to_entry(plan) for plan in plans)
    # The read starts a transaction; end it so a long-lived session holds no snapshot.
    await session.rollback()


async def refresh_forever(interval: float = _REFRESH_SECONDS) -> None:
    """Re-read the catalogue regularly, so an edit made on another worker is picked up."""
    while True:
        await asyncio.sleep(interval)
        try:
            async with SessionFactory() as session:
                await load_registry(session)
        except Exception:
            logger.exception("Could not refresh the plan catalogue")


# ---- Reading ----------------------------------------------------------------------------


async def get_plan(session: AsyncSession, key: str, *, lock: bool = False) -> Plan:
    statement = select(Plan).where(Plan.key == key).options(selectinload(Plan.prices))
    if lock:
        statement = statement.with_for_update()
    plan = await session.scalar(statement)
    if plan is None:
        raise NotFoundError("This plan does not exist.", code="plan_not_found")
    return plan


async def list_plans(session: AsyncSession) -> Sequence[Plan]:
    return (
        await session.scalars(
            select(Plan).options(selectinload(Plan.prices)).order_by(Plan.sort_rank, Plan.key)
        )
    ).all()


async def usage_counts(session: AsyncSession) -> dict[str, tuple[int, int]]:
    """Per plan key: (installers on it, of which with a Stripe subscription)."""
    rows = await session.execute(
        select(
            Installer.plan,
            func.count(),
            func.count(Installer.stripe_subscription_id),
        ).group_by(Installer.plan)
    )
    return {key: (installers, subscriptions) for key, installers, subscriptions in rows.all()}


async def require_signup_plan(session: AsyncSession, key: str) -> Plan:
    """A plan a new account may pick: the free default or an active plan with a price."""
    plan = await session.scalar(
        select(Plan).where(Plan.key == key).options(selectinload(Plan.prices))
    )
    if (
        plan is None
        or not plan.is_active
        or not (plan.is_default or _active_price(plan) is not None)
    ):
        raise FieldValidationError({"plan": "Choose one of the available plans."})
    return plan


async def require_assignable_plan(session: AsyncSession, key: str, *, field: str = "plan") -> Plan:
    """Any existing plan (the team may assign archived or unpriced ones too)."""
    plan = await session.get(Plan, key)
    if plan is None:
        raise FieldValidationError({field: "This plan does not exist."})
    return plan


# ---- Writing ----------------------------------------------------------------------------


async def _sync_to_stripe(plan: Plan, gateway: BillingGateway) -> None:
    """Create/update the plan's Stripe product and any price not yet in Stripe."""
    if not get_settings().stripe_configured:
        return
    has_price = any(price.is_active for price in plan.prices)
    if has_price or plan.stripe_product_id is not None:
        plan.stripe_product_id = await call_stripe(
            gateway.upsert_product(
                product_id=plan.stripe_product_id,
                key=plan.key,
                name=plan.name,
                description=plan.tagline,
            )
        )
    for price in plan.prices:
        if price.is_active and price.stripe_price_id is None and plan.stripe_product_id:
            price.stripe_price_id = await call_stripe(
                gateway.create_price(
                    product_id=plan.stripe_product_id,
                    key=plan.key,
                    amount_pence=price.amount_pence,
                    currency=price.currency,
                    interval=price.interval,
                )
            )


async def _archive_prices(price_ids: Sequence[str], gateway: BillingGateway) -> None:
    """Best effort: a retired price that stays active in Stripe is harmless to subscribers."""
    for price_id in price_ids:
        try:
            await call_stripe(gateway.archive_price(price_id))
        except Exception:
            logger.warning("Could not archive Stripe price %s", price_id)


def _set_price(session: AsyncSession, plan: Plan, amount_pence: int | None) -> list[str]:
    """Make `amount_pence` the plan's price. Returns Stripe ids of prices that were retired."""
    retired: list[str] = []
    current = _active_price(plan)
    if current is not None and current.amount_pence == amount_pence:
        return retired
    if current is not None:
        current.is_active = False
        if current.stripe_price_id:
            retired.append(current.stripe_price_id)
    if amount_pence is not None:
        price = PlanPrice(
            plan_key=plan.key, interval=INTERVAL, currency=CURRENCY, amount_pence=amount_pence
        )
        plan.prices.append(price)
    return retired


async def _only_popular(session: AsyncSession, key: str) -> None:
    await session.execute(
        update(Plan).where(Plan.key != key, Plan.is_popular.is_(True)).values(is_popular=False)
    )


async def create_plan(session: AsyncSession, data: PlanCreate, gateway: BillingGateway) -> Plan:
    if await session.get(Plan, data.key) is not None:
        raise FieldValidationError({"key": "A plan with this key already exists."})
    plan = Plan(
        key=data.key,
        name=data.name,
        tagline=data.tagline,
        features=data.features,
        is_active=data.is_active,
        is_popular=data.is_popular,
        sort_rank=data.sort_rank,
        receives_leads=data.receives_leads,
        accepts_direct_quotes=data.accepts_direct_quotes,
        full_public_profile=data.full_public_profile,
        public_service_limit=data.public_service_limit,
        max_gallery_photos=data.max_gallery_photos,
        prices=[],
    )
    session.add(plan)
    if data.price_pence is not None:
        _set_price(session, plan, data.price_pence)
    await session.flush()
    if data.is_popular:
        await _only_popular(session, plan.key)
    await _sync_to_stripe(plan, gateway)
    await session.commit()
    await load_registry(session)
    return await get_plan(session, data.key)


async def update_plan(
    session: AsyncSession, key: str, data: PlanUpdate, gateway: BillingGateway
) -> Plan:
    plan = await get_plan(session, key, lock=True)
    sent = data.model_fields_set

    if plan.is_default:
        if data.is_active is False:
            raise FieldValidationError({"is_active": "The default plan cannot be archived."})
        if data.price_pence is not None:
            raise FieldValidationError({"price_pence": "The default plan is always free."})

    for field in (
        "name",
        "features",
        "is_active",
        "is_popular",
        "sort_rank",
        "receives_leads",
        "accepts_direct_quotes",
        "full_public_profile",
        "max_gallery_photos",
    ):
        if field in sent:
            setattr(plan, field, getattr(data, field))
    # These two may be cleared with null (no tagline, no limit on services shown).
    for field in ("tagline", "public_service_limit"):
        if field in sent:
            setattr(plan, field, getattr(data, field))

    retired: list[str] = []
    if "price_pence" in sent:
        retired = _set_price(session, plan, data.price_pence)
        # Retire the old price before the new one is inserted (one active price per plan).
        await session.flush()
    if data.is_popular:
        await _only_popular(session, plan.key)

    await _sync_to_stripe(plan, gateway)
    await session.commit()
    await _archive_prices(retired, gateway)
    await load_registry(session)
    return await get_plan(session, key)


async def delete_plan(session: AsyncSession, key: str, gateway: BillingGateway) -> None:
    plan = await get_plan(session, key, lock=True)
    if plan.is_default:
        raise ConflictError("The default plan cannot be deleted.", code="default_plan")
    in_use = await session.scalar(
        select(func.count())
        .select_from(Installer)
        .where(
            (Installer.plan == key)
            | (Installer.pending_plan == key)
            | (Installer.requested_plan == key)
        )
    )
    if in_use:
        raise PlanInUseError
    stripe_prices = [price.stripe_price_id for price in plan.prices if price.stripe_price_id]
    product_id = plan.stripe_product_id
    await session.delete(plan)
    await session.commit()
    await load_registry(session)
    # Stripe keeps its records for the invoices already issued; just stop selling them.
    await _archive_prices([price for price in stripe_prices if price], gateway)
    if product_id and get_settings().stripe_configured:
        try:
            await call_stripe(gateway.archive_product(product_id))
        except Exception:
            logger.warning("Could not archive Stripe product %s", product_id)


async def sync_all(session: AsyncSession, gateway: BillingGateway) -> int:
    """Create whatever is missing in Stripe for every plan; returns how many plans changed."""
    changed = 0
    for plan in await list_plans(session):
        before = (
            plan.stripe_product_id,
            tuple(price.stripe_price_id for price in plan.prices),
        )
        await _sync_to_stripe(plan, gateway)
        after = (plan.stripe_product_id, tuple(price.stripe_price_id for price in plan.prices))
        changed += before != after
    await session.commit()
    return changed


async def ensure_stripe_price(
    session: AsyncSession, key: str, gateway: BillingGateway
) -> PlanPrice:
    """The plan's current price with its Stripe id, creating it in Stripe if it was not yet."""
    plan = await get_plan(session, key, lock=True)
    price = _active_price(plan)
    if price is None or not plan.is_active or plan.is_default:
        raise FieldValidationError({"plan": "This plan cannot be bought."})
    if price.stripe_price_id is None:
        await _sync_to_stripe(plan, gateway)
        await session.commit()
    return price
