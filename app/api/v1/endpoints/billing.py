"""Subscription checkout, billing portal and the Stripe webhook."""

from typing import Annotated

from fastapi import APIRouter, Header, Request

from app.api.deps import BillingGatewayDep, CurrentUserDep, InstallerDep, SessionDep
from app.schemas.billing import CheckoutRequest, SessionUrl
from app.services import billing

router = APIRouter(prefix="/billing", tags=["billing"])


@router.post("/checkout-session")
async def create_checkout_session(
    data: CheckoutRequest,
    user: CurrentUserDep,
    installer: InstallerDep,
    session: SessionDep,
    gateway: BillingGatewayDep,
) -> SessionUrl:
    url = await billing.create_checkout_session(session, installer, user.email, data.plan, gateway)
    return SessionUrl(url=url)


@router.post("/portal-session")
async def create_portal_session(installer: InstallerDep, gateway: BillingGatewayDep) -> SessionUrl:
    return SessionUrl(url=await billing.create_portal_session(installer, gateway))


@router.post("/webhook", summary="Stripe webhook (authenticated by its signature)")
async def stripe_webhook(
    request: Request,
    session: SessionDep,
    gateway: BillingGatewayDep,
    stripe_signature: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    event = billing.verify_webhook(await request.body(), stripe_signature)
    await billing.handle_event(session, event, gateway)
    return {"received": True}
