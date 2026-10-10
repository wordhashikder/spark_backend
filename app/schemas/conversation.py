"""In-app messages and priced quotes between installers and homeowners."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import MessageSender, OfferStatus
from app.models import Conversation, ConversationMessage, Offer
from app.models.base import utcnow
from app.schemas.common import text

MessageBody = Annotated[str, text(1, 5000)]
MAX_OFFER_VALIDITY = timedelta(days=365)


class ConversationStart(BaseModel):
    """Open the conversation for a lead or for a direct enquiry (exactly one)."""

    lead_id: uuid.UUID | None = None
    enquiry_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.lead_id is None) == (self.enquiry_id is None):
            raise ValueError("Provide either lead_id or enquiry_id.")
        return self


class MessageCreate(BaseModel):
    body: MessageBody


class OfferCreate(BaseModel):
    amount: Annotated[Decimal, Field(gt=0, le=Decimal("1000000"), max_digits=10, decimal_places=2)]
    includes_vat: bool = True
    description: Annotated[str, text(10, 5000)]
    valid_until: date | None = None
    message: Annotated[str, text(1, 2000)] | None = None

    @model_validator(mode="after")
    def _valid_until_in_future(self) -> Self:
        today = utcnow().date()
        if self.valid_until is not None and not (
            today <= self.valid_until <= today + MAX_OFFER_VALIDITY
        ):
            raise ValueError("The quote must be valid from today and for at most a year.")
        return self


class OfferResponse(BaseModel):
    decision: Literal["accept", "decline"]
    note: Annotated[str, text(1, 2000)] | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sender: MessageSender
    body: str
    created_at: datetime


class OfferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference: str
    amount: Decimal
    includes_vat: bool
    description: str
    valid_until: date | None
    status: OfferStatus
    responded_at: datetime | None
    response_note: str | None
    created_at: datetime


class ConversationJob(BaseModel):
    """What the conversation is about: a matched quote request or a direct enquiry."""

    kind: Literal["lead", "enquiry"]
    reference: str | None
    summary: list[tuple[str, str]]
    message: str | None
    phone: str | None
    created_at: datetime


class ConversationSummary(BaseModel):
    id: uuid.UUID
    installer_id: uuid.UUID
    installer_name: str
    installer_slug: str
    homeowner_name: str
    homeowner_email: str
    kind: Literal["lead", "enquiry"]
    lead_id: uuid.UUID | None
    enquiry_id: uuid.UUID | None
    last_message_at: datetime
    last_message: str | None
    last_sender: MessageSender | None
    unread: bool
    offer_count: int
    latest_offer_status: OfferStatus | None
    created_at: datetime

    @classmethod
    def build(
        cls,
        conversation: Conversation,
        last: ConversationMessage | None,
        *,
        reader: Literal["installer", "homeowner", "admin"],
    ) -> Self:
        offers = conversation.offers
        read_at = (
            conversation.installer_read_at
            if reader == "installer"
            else conversation.homeowner_read_at
        )
        other = MessageSender.HOMEOWNER if reader == "installer" else MessageSender.INSTALLER
        unread = (
            reader != "admin"
            and last is not None
            and last.sender in (other, MessageSender.TEAM)
            and (read_at is None or last.created_at > read_at)
        )
        return cls(
            id=conversation.id,
            installer_id=conversation.installer_id,
            installer_name=conversation.installer.business_name,
            installer_slug=conversation.installer.slug,
            homeowner_name=conversation.homeowner_name,
            homeowner_email=conversation.homeowner_email,
            kind="lead" if conversation.quote_match_id else "enquiry",
            lead_id=conversation.quote_match_id,
            enquiry_id=conversation.enquiry_id,
            last_message_at=conversation.last_message_at,
            last_message=last.body[:200] if last else None,
            last_sender=last.sender if last else None,
            unread=unread,
            offer_count=len(offers),
            latest_offer_status=offers[-1].status if offers else None,
            created_at=conversation.created_at,
        )


class ConversationDetail(BaseModel):
    id: uuid.UUID
    installer_name: str
    installer_slug: str
    homeowner_name: str
    homeowner_email: str | None
    job: ConversationJob
    messages: list[MessageOut]
    offers: list[OfferOut]
    created_at: datetime


def offer_out(offer: Offer) -> OfferOut:
    return OfferOut.model_validate(offer)


class InstallerQuote(OfferOut):
    """A quote in the installer's list, with who it was sent to."""

    conversation_id: uuid.UUID
    homeowner_name: str

    @classmethod
    def build(cls, offer: Offer, conversation: Conversation) -> Self:
        return cls(
            **OfferOut.model_validate(offer).model_dump(),
            conversation_id=conversation.id,
            homeowner_name=conversation.homeowner_name,
        )


class InstallerSummary(BaseModel):
    """The installer dashboard's headline numbers."""

    plan: str
    receives_leads: bool
    is_claimed: bool
    status: str
    new_leads: int
    leads_total: int
    enquiries_total: int
    unread_conversations: int
    open_quotes: int
    accepted_quotes: int
    rating_avg: float | None
    review_count: int
