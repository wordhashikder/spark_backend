"""
Accreditation schemes: what the website shows on a profile card, and the team's management.
"""

import uuid
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.common import blank_as_none, text

KEY_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"

SchemeName = Annotated[str, text(2, 60)]
Badge = Annotated[Annotated[str, text(1, 40)] | None, blank_as_none]
CardTitle = Annotated[str, text(2, 80)]
CardText = Annotated[str, text(10, 400)]
SchemeKey = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=40, pattern=KEY_PATTERN)
]


class AccreditationSchemePublic(BaseModel):
    """What a card needs. `href` is the scheme's page, only once it is published and has content."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    badge: str | None
    card_title: str
    card_text: str
    is_active: bool
    href: str | None = None


class AdminAccreditationScheme(AccreditationSchemePublic):
    position: int
    installer_count: int
    page_id: uuid.UUID | None
    page_path: str | None
    page_published: bool
    page_has_content: bool


class AccreditationSchemeCreate(BaseModel):
    name: SchemeName
    badge: Badge = None
    card_title: CardTitle
    card_text: CardText
    position: Annotated[int, Field(ge=0, le=10_000)] | None = None


class AccreditationSchemeUpdate(BaseModel):
    name: SchemeName | None = None
    badge: Badge = None
    card_title: CardTitle | None = None
    card_text: CardText | None = None
    position: Annotated[int, Field(ge=0, le=10_000)] | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        for name in ("name", "card_title", "card_text", "position", "is_active"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be empty.")
        return self
