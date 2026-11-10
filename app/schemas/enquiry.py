"""Direct enquiries: the "Request a Quote" form on an installer's profile."""

import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field

from app.core.names import given_name
from app.models import InstallerEnquiry
from app.schemas.common import Email, Phone, blank_as_none, text


class EnquiryCreate(BaseModel):
    name: Annotated[str, text(2, 80)]
    email: Email
    # Optional, as on the quote form: blank means "contact me by email".
    phone: Annotated[Phone | None, blank_as_none] = None
    message: Annotated[str, text(10, 3000)]
    # Honeypot: hidden from people, so only bots fill it in.
    website: str | None = Field(default=None, max_length=2000)


class Enquiry(BaseModel):
    """An enquiry as its installer sees it: neither the customer's email address nor their
    phone number is included, and the name is the first name only. The installer answers
    through PickASparky messages."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    message: str
    created_at: datetime

    @classmethod
    def for_installer(cls, enquiry: InstallerEnquiry) -> Self:
        """The installer's copy: the customer's first name only."""
        return cls(
            id=enquiry.id,
            name=given_name(enquiry.name),
            message=enquiry.message,
            created_at=enquiry.created_at,
        )


class AdminEnquiry(Enquiry):
    """An enquiry as the team sees it, with the customer's email address and phone."""

    email: str
    phone: str | None
    installer_id: uuid.UUID
    installer_slug: str
    installer_name: str
    # False: the installer is on the Free plan, so the team received the request instead.
    sent_to_installer: bool

    @classmethod
    def from_enquiry(cls, enquiry: InstallerEnquiry) -> Self:
        return cls(
            id=enquiry.id,
            name=enquiry.name,
            email=enquiry.email,
            phone=enquiry.phone,
            message=enquiry.message,
            created_at=enquiry.created_at,
            installer_id=enquiry.installer_id,
            installer_slug=enquiry.installer.slug,
            installer_name=enquiry.installer.business_name,
            sent_to_installer=enquiry.sent_to_installer,
        )
