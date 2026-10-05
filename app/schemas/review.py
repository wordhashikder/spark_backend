"""Review request and response bodies."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import OpaqueToken, blank_as_none, text


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rating: int
    title: str
    body: str
    author_name: str
    author_location: str | None
    verified: bool
    created_at: datetime


class ReviewInvite(BaseModel):
    installer_name: str
    installer_slug: str


class ReviewCreate(BaseModel):
    token: OpaqueToken
    rating: int = Field(ge=1, le=5)
    title: Annotated[str, text(3, 80)]
    body: Annotated[str, text(20, 1500)]
    author_name: Annotated[str, text(2, 60)]
    author_location: Annotated[Annotated[str, text(1, 60)] | None, blank_as_none] = None
