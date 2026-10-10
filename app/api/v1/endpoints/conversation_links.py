"""The homeowner's private conversation page: read, reply, accept or decline a quote.

Homeowners need no account: the emailed link carries a signed token. The token travels in
the request body (never the URL), so it does not end up in access logs.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import EmailQueueDep, SessionDep
from app.core.rate_limit import rate_limit
from app.schemas.common import OpaqueToken
from app.schemas.conversation import (
    ConversationDetail,
    MessageBody,
    MessageOut,
    OfferOut,
    OfferResponse,
)
from app.services import conversations

router = APIRouter(prefix="/conversation-links", tags=["conversations"])


class LinkToken(BaseModel):
    token: OpaqueToken


class LinkMessage(LinkToken):
    body: MessageBody


class LinkOfferResponse(LinkToken, OfferResponse):
    pass


@router.post("/view", dependencies=[Depends(rate_limit("conversation-view", "60/minute"))])
async def view(data: LinkToken, session: SessionDep) -> ConversationDetail:
    return await conversations.get_for_homeowner(session, data.token)


@router.post(
    "/messages",
    status_code=201,
    dependencies=[Depends(rate_limit("conversation-reply", "30/hour"))],
)
async def reply(data: LinkMessage, session: SessionDep, emails: EmailQueueDep) -> MessageOut:
    message, outbox = await conversations.homeowner_message(session, data.token, data.body)
    emails.send(outbox)
    return message


@router.post(
    "/quotes/{offer_id}",
    dependencies=[Depends(rate_limit("conversation-respond", "30/hour"))],
)
async def respond(
    offer_id: Annotated[uuid.UUID, "the quote being answered"],
    data: LinkOfferResponse,
    session: SessionDep,
    emails: EmailQueueDep,
) -> OfferOut:
    offer, outbox = await conversations.respond_to_offer(
        session, data.token, offer_id, data.decision, data.note
    )
    emails.send(outbox)
    return offer
