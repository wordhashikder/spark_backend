"""Quote request and lead bodies."""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.enums import (
    CHARGER_FOLLOWUPS,
    ChargerFollowup,
    ChargerLocation,
    ExistingCharger,
    FuseBoxDistance,
    InstallationType,
    LeadStatus,
    OfferStatus,
    Timing,
)
from app.core.exceptions import FieldValueError
from app.models import QuoteMatch
from app.schemas.common import Email, Phone, Postcode, blank_as_none, text
from app.services.geocoding import outward_code


class QuoteCreate(BaseModel):
    postcode: Postcode
    installation_type: InstallationType
    charger_location: ChargerLocation
    existing_charger: ExistingCharger
    charger_followup: ChargerFollowup
    fuse_box_distance: FuseBoxDistance
    vehicle: Annotated[Annotated[str, text(1, 120)] | None, blank_as_none] = None
    vehicle_undecided: bool = False
    timing: Timing
    notes: Annotated[Annotated[str, text(1, 1000)] | None, blank_as_none] = None
    first_name: Annotated[str, text(1, 60)]
    email: Email
    # Optional: blank means the customer prefers to be contacted by email.
    phone: Annotated[Phone | None, blank_as_none] = None
    consent: bool
    installer_slug: Annotated[Annotated[str, text(1, 140)] | None, blank_as_none] = None
    # Honeypot: hidden from people, so only bots fill it in.
    website: str | None = Field(default=None, max_length=2000)

    @field_validator("consent")
    @classmethod
    def _consent_is_required(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Please confirm we can share your request with matched installers.")
        return value

    @model_validator(mode="after")
    def _followup_matches_branch(self) -> Self:
        if self.charger_followup not in CHARGER_FOLLOWUPS[self.existing_charger]:
            raise FieldValueError(
                "charger_followup", "This answer does not apply to the option you chose."
            )
        return self


class QuoteCreated(BaseModel):
    reference: str
    postcode: str
    matched_installers: int
    # Automatic matching is off: the team chooses the installers and emails the homeowner.
    held: bool = False


class LeadQuote(BaseModel):
    """An enquiry as an installer sees it.

    Installers without full access (the Free plan) get the headline only: first name, town,
    service and timeframe. The answers, notes and contact details are `None` until they
    upgrade.
    """

    reference: str
    postcode: str
    district: str | None
    installation_type: InstallationType
    charger_location: ChargerLocation | None
    existing_charger: ExistingCharger | None
    charger_followup: ChargerFollowup | None
    fuse_box_distance: FuseBoxDistance | None
    vehicle: str | None
    vehicle_undecided: bool
    timing: Timing
    notes: str | None
    first_name: str
    email: str | None
    phone: str | None


class LeadProgress(BaseModel):
    """Where a lead stands, for the installer's lead cards."""

    # Installers the request went to, and quotes they have sent (withdrawn ones excluded).
    installers_matched: int = 0
    quotes_sent: int = 0
    # Installers who have answered (a message or a quote): they hold the request's places.
    responders: int = 0
    # How many installers may quote one request (Settings), so cards can say "2 slots left".
    slots_total: int = 5
    # From the installer's base to the job (null when the postcode was not located).
    distance_miles: float | None = None
    # The installer's own conversation and latest quote for this lead, if any.
    conversation_id: uuid.UUID | None = None
    my_quote_status: OfferStatus | None = None


LeadAccess = Literal["open", "upgrade_required", "full"]


class Lead(BaseModel):
    id: uuid.UUID
    status: LeadStatus
    created_at: datetime
    quote: LeadQuote
    progress: LeadProgress | None = None
    # open: the installer can view and respond. upgrade_required: Free plan. full: the
    # request already has its maximum number of responding installers.
    access: LeadAccess = "open"

    @classmethod
    def from_match(cls, match: QuoteMatch, *, full_access: bool) -> Self:
        """Build a lead, showing only the headline unless the plan has full lead access."""
        quote = match.quote_request
        return cls(
            id=match.id,
            status=match.status,
            created_at=match.created_at,
            access="open" if full_access else "upgrade_required",
            quote=LeadQuote(
                reference=quote.reference,
                postcode=quote.postcode if full_access else outward_code(quote.postcode),
                district=quote.district,
                installation_type=quote.installation_type,
                charger_location=quote.charger_location if full_access else None,
                existing_charger=quote.existing_charger if full_access else None,
                charger_followup=quote.charger_followup if full_access else None,
                fuse_box_distance=quote.fuse_box_distance if full_access else None,
                vehicle=quote.vehicle if full_access else None,
                vehicle_undecided=quote.vehicle_undecided if full_access else False,
                timing=quote.timing,
                notes=quote.notes if full_access else None,
                first_name=quote.first_name,
                email=quote.email if full_access else None,
                phone=quote.phone if full_access else None,
            ),
        )


class LeadUpdate(BaseModel):
    status: LeadStatus

    @field_validator("status")
    @classmethod
    def _cannot_return_to_sent(cls, value: LeadStatus) -> LeadStatus:
        if value is LeadStatus.SENT:
            raise ValueError("Choose one of the available options.")
        return value
