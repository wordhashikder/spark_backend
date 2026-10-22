"""The installer's subscription: plan changes, cancellation, history, and the Stripe webhook."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request

from app.api.deps import (
    BillingGatewayDep,
    CurrentUserDep,
    EmailQueueDep,
    InstallerDep,
    PageDep,
    SessionDep,
)
from app.core.rate_limit import rate_limit
from app.schemas.billing import (
    ActivityOut,
    BillingSummary,
    ChangePlanRequest,
    CheckoutRequest,
    CheckoutStatus,
    InvoiceOut,
    PortalRequest,
    SessionUrl,
)
from app.schemas.common import Paginated
from app.services import billing

router = APIRouter(prefix="/billing", tags=["billing"])

_change_limit = [Depends(rate_limit("billing-change", "30/hour"))]


@router.get("/summary")
async def get_summary(installer: InstallerDep, session: SessionDep) -> BillingSummary:
    """The current plan, renewal date, any booked change, and the plans on offer."""
    return await billing.summary(session, installer)


@router.post("/checkout-session", dependencies=_change_limit)
async def create_checkout_session(
    data: CheckoutRequest,
    user: CurrentUserDep,
    installer: InstallerDep,
    session: SessionDep,
    gateway: BillingGatewayDep,
) -> SessionUrl:
    """Start Stripe Checkout for a first subscription."""
    url = await billing.create_checkout_session(
        session, installer, user.email, data.plan, gateway, data.return_to
    )
    return SessionUrl(url=url)


@router.get("/checkout-status")
async def get_checkout_status(
    session_id: Annotated[str, Query(min_length=8, max_length=255, pattern=r"^cs_[A-Za-z0-9_]+$")],
    installer: InstallerDep,
    session: SessionDep,
    gateway: BillingGatewayDep,
) -> CheckoutStatus:
    """Where a checkout stands after Stripe sends the installer back (the success page)."""
    return await billing.checkout_status(session, installer, session_id, gateway)


@router.post("/change-plan", dependencies=_change_limit)
async def change_plan(
    data: ChangePlanRequest,
    installer: InstallerDep,
    session: SessionDep,
    gateway: BillingGatewayDep,
) -> BillingSummary:
    """Upgrade now (prorated) or book a downgrade for the end of the period."""
    return await billing.change_plan(session, installer, data.plan, gateway)


@router.post("/cancel-change", dependencies=_change_limit)
async def cancel_pending_change(
    installer: InstallerDep, session: SessionDep, gateway: BillingGatewayDep
) -> BillingSummary:
    """Drop a booked downgrade and stay on the current plan."""
    return await billing.cancel_pending_change(session, installer, gateway)


@router.post("/cancel", dependencies=_change_limit)
async def cancel_subscription(
    installer: InstallerDep, session: SessionDep, gateway: BillingGatewayDep
) -> BillingSummary:
    """Switch auto-renewal off; the plan runs until the end of the paid period."""
    return await billing.cancel_subscription(session, installer, gateway)


@router.post("/resume", dependencies=_change_limit)
async def resume_subscription(
    installer: InstallerDep, session: SessionDep, gateway: BillingGatewayDep
) -> BillingSummary:
    """Switch auto-renewal back on."""
    return await billing.resume_subscription(session, installer, gateway)


@router.post("/portal-session", dependencies=_change_limit)
async def create_portal_session(
    installer: InstallerDep, gateway: BillingGatewayDep, data: PortalRequest | None = None
) -> SessionUrl:
    """Open Stripe's billing portal (payment method, receipts)."""
    return_to = data.return_to if data else "dashboard"
    return SessionUrl(url=await billing.create_portal_session(installer, gateway, return_to))


@router.get("/invoices")
async def list_invoices(
    installer: InstallerDep, session: SessionDep, page: PageDep
) -> Paginated[InvoiceOut]:
    """Payment history, newest first."""
    rows, total = await billing.list_invoices(
        session, installer.id, offset=page.offset, limit=page.page_size
    )
    return Paginated.build(
        [InvoiceOut.from_invoice(row) for row in rows],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/activity")
async def list_activity(installer: InstallerDep, session: SessionDep) -> list[ActivityOut]:
    """Plan changes, cancellations and failed payments, newest first."""
    rows = await billing.list_activity(session, installer.id)
    return [ActivityOut.from_activity(row) for row in rows]


@router.post("/webhook", summary="Stripe webhook (authenticated by its signature)")
async def stripe_webhook(
    request: Request,
    session: SessionDep,
    gateway: BillingGatewayDep,
    email_queue: EmailQueueDep,
    stripe_signature: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    event = billing.verify_webhook(await request.body(), stripe_signature)
    outbox = await billing.handle_event(session, event, gateway)
    email_queue.send(outbox)
    return {"received": True}
