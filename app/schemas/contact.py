"""Contact form request body."""

from typing import Annotated

from pydantic import BaseModel, Field

from app.core.enums import ContactSubject
from app.schemas.common import Email, text


class ContactCreate(BaseModel):
    name: Annotated[str, text(2, 80)]
    email: Email
    subject: ContactSubject
    message: Annotated[str, text(10, 3000)]
    # Honeypot: hidden from people, so only bots fill it in.
    website: str | None = Field(default=None, max_length=2000)
