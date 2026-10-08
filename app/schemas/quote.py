"""Quote request and lead bodies."""

import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.enums import (
    CHARGER_FOLLOWUPS,
    ChargerFollowup,
    ChargerLocation,
    ExistingCharger,
    FuseBoxDistance,
    InstallationType,
    LeadStatus,
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


class LeadQuote(BaseModel):
    reference: str
    postcode: str
    district: str | None
    installation_type: InstallationType
    charger_location: ChargerLocation
    existing_charger: ExistingCharger
    charger_followup: ChargerFollowup
    fuse_box_distance: FuseBoxDistance
    vehicle: str | None
    vehicle_undecided: bool
    timing: Timing
    notes: str | None
    first_name: str
    email: str | None
    phone: str | None


class Lead(BaseModel):
    id: uuid.UUID
    status: LeadStatus
    created_at: datetime
    quote: LeadQuote

    @classmethod
    def from_match(cls, match: QuoteMatch, *, reveal_contact: bool) -> Self:
        """Build a lead, withholding contact details unless the plan receives leads."""
        quote = match.quote_request
        return cls(
            id=match.id,
            status=match.status,
            created_at=match.created_at,
            quote=LeadQuote(
                reference=quote.reference,
                postcode=quote.postcode if reveal_contact else outward_code(quote.postcode),
                district=quote.district,
                installation_type=quote.installation_type,
                charger_location=quote.charger_location,
                existing_charger=quote.existing_charger,
                charger_followup=quote.charger_followup,
                fuse_box_distance=quote.fuse_box_distance,
                vehicle=quote.vehicle,
                vehicle_undecided=quote.vehicle_undecided,
                timing=quote.timing,
                notes=quote.notes,
                first_name=quote.first_name,
                email=quote.email if reveal_contact else None,
                phone=quote.phone if reveal_contact else None,
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
