"""Plan capability table: the single source of truth for free / pro / premium rules."""

from dataclasses import dataclass

from sqlalchemy import ColumnElement, case

from app.core.enums import Plan


@dataclass(frozen=True, slots=True)
class PlanCapabilities:
    receives_leads: bool
    accepts_direct_quotes: bool
    full_public_profile: bool
    public_service_limit: int | None
    sort_rank: int
    max_gallery_photos: int


PLAN_CAPABILITIES: dict[Plan, PlanCapabilities] = {
    Plan.FREE: PlanCapabilities(
        receives_leads=False,
        accepts_direct_quotes=False,
        full_public_profile=False,
        public_service_limit=2,
        sort_rank=0,
        max_gallery_photos=0,
    ),
    Plan.PRO: PlanCapabilities(
        receives_leads=True,
        accepts_direct_quotes=True,
        full_public_profile=True,
        public_service_limit=None,
        sort_rank=1,
        max_gallery_photos=12,
    ),
    Plan.PREMIUM: PlanCapabilities(
        receives_leads=True,
        accepts_direct_quotes=True,
        full_public_profile=True,
        public_service_limit=None,
        sort_rank=2,
        max_gallery_photos=24,
    ),
}

LEAD_RECEIVING_PLANS: tuple[Plan, ...] = tuple(
    plan for plan, capabilities in PLAN_CAPABILITIES.items() if capabilities.receives_leads
)
PAID_PLANS: tuple[Plan, ...] = (Plan.PRO, Plan.PREMIUM)


def capabilities_for(plan: Plan) -> PlanCapabilities:
    return PLAN_CAPABILITIES[plan]


def sort_rank_expression(plan_column: ColumnElement[Plan]) -> ColumnElement[int]:
    """SQL expression yielding the listing rank of the plan stored in `plan_column`."""
    ranks = {plan: capabilities.sort_rank for plan, capabilities in PLAN_CAPABILITIES.items()}
    return case(ranks, value=plan_column, else_=0)
