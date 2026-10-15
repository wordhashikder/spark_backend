"""The customer's own view: their requests, the quotes received and their messages."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.core.enums import OfferStatus
from app.schemas.common import Email, Phone, blank_as_none, text

OpaqueSessionToken = Annotated[str, Field(min_length=20, max_length=200)]


class LinkRequest(BaseModel):
    email: Email


class LinkVerify(BaseModel):
    token: Annotated[str, Field(min_length=20, max_length=200)]


class CustomerOut(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    phone: str | None
    created_at: datetime


class CustomerUpdate(BaseModel):
    first_name: Annotated[str, text(1, 60)] | None = None
    phone: Annotated[Phone | None, blank_as_none] = None


class CustomerSessionOut(BaseModel):
    """What the website stores in its httpOnly cookie after a magic link is used."""

    session_token: str
    expires_in: int
    customer: CustomerOut


class InstallerBrief(BaseModel):
    slug: str
    business_name: str
    town: str
    logo_url: str | None
    rating_avg: float | None
    review_count: int
    verified: bool
    years_experience: int | None
    accreditations: list[str]
    plan: str


class JourneyStep(BaseModel):
    key: str
    label: str
    state: Literal["done", "current", "upcoming"]


class CustomerQuoteOut(BaseModel):
    id: uuid.UUID
    reference: str
    amount: Decimal
    includes_vat: bool
    description: str
    valid_until: date | None
    status: OfferStatus
    created_at: datetime
    conversation_id: uuid.UUID
    installer: InstallerBrief
    # "lowest" marks the cheapest open quote when there are several to compare.
    highlight: Literal["lowest"] | None = None


class MatchedInstallerOut(BaseModel):
    installer: InstallerBrief
    state: Literal["awaiting_quote", "quoted", "declined", "accepted"]
    conversation_id: uuid.UUID | None


class RequestSummaryOut(BaseModel):
    id: uuid.UUID
    reference: str
    postcode: str
    district: str | None
    installation_type: str
    timing: str
    status: str
    status_label: str
    status_detail: str
    created_at: datetime
    installers_matched: int
    quotes_received: int
    slots_total: int
    average_price: Decimal | None
    lowest_price: Decimal | None
    unread_messages: int


class RequestDetailOut(RequestSummaryOut):
    answers: list[tuple[str, str]]
    journey: list[JourneyStep]
    quotes: list[CustomerQuoteOut]
    installers: list[MatchedInstallerOut]
    conversation_ids: list[uuid.UUID]


class CustomerOverview(BaseModel):
    customer: CustomerOut
    requests: list[RequestSummaryOut]
    unread_messages: int


class CustomerMessage(BaseModel):
    body: Annotated[str, text(1, 5000)]


class CustomerOfferDecision(BaseModel):
    decision: Literal["accept", "decline"]
    note: Annotated[str, text(1, 2000)] | None = None


class CustomerEmail(BaseModel):
    email: Email
