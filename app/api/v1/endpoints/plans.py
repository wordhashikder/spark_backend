"""The public plan catalogue (pricing page, sign-up and upgrade screens)."""

from fastapi import APIRouter, Response

from app.core.plans import registry
from app.schemas.plan import PublicPlan

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("")
async def list_plans(response: Response) -> list[PublicPlan]:
    """Plans a business can choose today: the free plan and every active, priced plan."""
    response.headers["Cache-Control"] = "public, max-age=60"
    return [
        PublicPlan.from_entry(entry)
        for entry in registry.all()
        if entry.is_active and (entry.is_default or entry.is_purchasable)
    ]
