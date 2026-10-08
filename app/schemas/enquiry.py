"""Direct enquiries: the "Request a Quote" form on an installer's profile."""

import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field

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
    """An enquiry as its installer sees it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    phone: str | None
    message: str
    created_at: datetime


class AdminEnquiry(Enquiry):
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
