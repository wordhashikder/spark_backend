"""Editable website content as the website and the Dashboard see it."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PublicContent(BaseModel):
    """A page's content for the website: the admin's version, or the original wording."""

    key: str
    content: dict[str, Any]
    updated_at: datetime | None


class ContentSummary(BaseModel):
    key: str
    label: str
    group: str
    description: str
    path: str | None
    # True once the admin has saved the page (it differs from, or replaced, the original).
    customised: bool
    updated_at: datetime | None
    updated_by: str | None
    revision_count: int


class ContentDocument(BaseModel):
    """Everything the Dashboard's editor needs for one page."""

    model_config = {"populate_by_name": True}

    schema_: dict[str, Any] = Field(alias="schema", serialization_alias="schema")
    defaults: dict[str, Any]
    content: dict[str, Any]
    customised: bool
    updated_at: datetime | None
    updated_by: str | None
    tokens: dict[str, str]


class ContentUpdate(BaseModel):
    content: dict[str, Any]


class ContentRevision(BaseModel):
    id: uuid.UUID
    action: str
    created_at: datetime
    author: str | None
