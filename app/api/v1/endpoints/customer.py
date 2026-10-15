"""The customer's quote dashboard API.

Customers have no password. A magic link, emailed with every quote request, is exchanged
for a session token; the website keeps that token in an httpOnly cookie and sends it as a
bearer token from its server. Everything here is scoped to the signed-in customer.
"""

import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from limits import parse

from app.api.deps import (
    CurrentCustomerDep,
    EmailQueueDep,
    PageDep,
    PlatformSettingsDep,
    SessionDep,
)
from app.core.rate_limit import RateLimiter, rate_limit
from app.schemas.common import Paginated
from app.schemas.conversation import ConversationDetail, ConversationSummary, MessageOut, OfferOut
from app.schemas.customer import (
    CustomerMessage,
    CustomerOfferDecision,
    CustomerOut,
    CustomerOverview,
    CustomerSessionOut,
    CustomerUpdate,
    LinkRequest,
    LinkVerify,
    RequestDetailOut,
)
from app.services import conversations, customers

router = APIRouter(prefix="/customer", tags=["customer"])
_bearer = HTTPBearer(auto_error=False)


@router.post(
    "/auth/request-link",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("customer-link", "10/hour"))],
)
async def request_link(
    data: LinkRequest, request: Request, session: SessionDep, emails: EmailQueueDep
) -> dict[str, bool]:
    """Email a fresh magic link. The answer is the same whether or not the address is known."""
    limiter: RateLimiter = request.app.state.rate_limiter
    digest = hashlib.sha256(data.email.encode()).hexdigest()
    await limiter.hit("customer-link-email", parse("3/hour"), digest)
    emails.send(await customers.request_link(session, data.email))
    return {"sent": True}


@router.post("/auth/verify", dependencies=[Depends(rate_limit("customer-verify", "30/hour"))])
async def verify(data: LinkVerify, session: SessionDep) -> CustomerSessionOut:
    return await customers.verify_link(session, data.token)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    session: SessionDep,
    credentials: Annotated[object, Depends(_bearer)],
) -> Response:
    if isinstance(credentials, HTTPAuthorizationCredentials):
        await customers.sign_out(session, credentials.credentials)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me")
async def me(customer: CurrentCustomerDep) -> CustomerOut:
    return customers.profile(customer)


@router.patch("/me")
async def update_me(
    data: CustomerUpdate, customer: CurrentCustomerDep, session: SessionDep
) -> CustomerOut:
    return await customers.update_profile(session, customer, data.first_name, data.phone)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(customer: CurrentCustomerDep, session: SessionDep) -> Response:
    """Remove the customer record and sign-in data. Requests already shared stay with the
    installers who received them."""
    await customers.erase(session, customer)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/overview")
async def overview(
    customer: CurrentCustomerDep, session: SessionDep, platform: PlatformSettingsDep
) -> CustomerOverview:
    requests, unread = await customers.overview(
        session, customer, platform.lead_matching.max_installers
    )
    return CustomerOverview(
        customer=customers.profile(customer), requests=requests, unread_messages=unread
    )


@router.get("/requests/{request_id}")
async def request_detail(
    request_id: uuid.UUID,
    customer: CurrentCustomerDep,
    session: SessionDep,
    platform: PlatformSettingsDep,
) -> RequestDetailOut:
    return await customers.request_detail(
        session, customer, request_id, platform.lead_matching.max_installers
    )


@router.get("/conversations")
async def list_conversations(
    customer: CurrentCustomerDep, session: SessionDep, page: PageDep
) -> Paginated[ConversationSummary]:
    items, total = await conversations.list_for_customer(
        session, customer, offset=page.offset, limit=page.page_size
    )
    return Paginated.build(items, total=total, page=page.page, page_size=page.page_size)


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID, customer: CurrentCustomerDep, session: SessionDep
) -> ConversationDetail:
    return await conversations.get_for_customer(session, customer, conversation_id)


@router.post(
    "/conversations/{conversation_id}/messages",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("customer-reply", "60/hour"))],
)
async def send_message(
    conversation_id: uuid.UUID,
    data: CustomerMessage,
    customer: CurrentCustomerDep,
    session: SessionDep,
    emails: EmailQueueDep,
) -> MessageOut:
    message, outbox = await conversations.customer_message(
        session, customer, conversation_id, data.body
    )
    emails.send(outbox)
    return message


@router.post(
    "/quotes/{offer_id}/respond",
    dependencies=[Depends(rate_limit("customer-respond", "30/hour"))],
)
async def respond(
    offer_id: uuid.UUID,
    data: CustomerOfferDecision,
    customer: CurrentCustomerDep,
    session: SessionDep,
    emails: EmailQueueDep,
) -> OfferOut:
    offer, outbox = await conversations.customer_respond_to_offer(
        session, customer, offer_id, data.decision, data.note
    )
    emails.send(outbox)
    return offer
