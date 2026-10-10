"""Location and postcode lookup responses, and the admin's location content edits."""

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.core.enums import DirectoryColumn
from app.schemas.common import ImageUrl, blank_as_none, text


class LocationRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str


class LocationSummary(LocationRef):
    region: str
    latitude: float
    longitude: float
    installer_count: int


class LocationDetail(LocationSummary):
    intro: str | None
    image_url: str | None
    image_alt: str | None
    image_credit: str | None
    # Search snippet overrides; null means the page uses its standard wording.
    seo_title: str | None = None
    seo_description: str | None = None


class LocationDirectory(BaseModel):
    """The four directory columns, each in display order."""

    nearby: list[LocationRef]
    popular: list[LocationRef]
    more_in_area: list[LocationRef]
    other: list[LocationRef]


class PostcodeLookup(BaseModel):
    postcode: str
    district: str | None
    region: str | None
    installers_in_range: int


class AdminLocation(BaseModel):
    """Everything about a location the back office shows, including its managed content."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    region: str
    latitude: float
    longitude: float
    directory_column: DirectoryColumn | None
    directory_position: int | None
    intro: str | None
    image_url: str | None
    image_alt: str | None
    image_credit: str | None
    seo_title: str | None
    seo_description: str | None
    installer_count: int = 0


class AdminLocationUpdate(BaseModel):
    """Partial update: only the fields sent are changed; send `null` to clear one."""

    intro: Annotated[Annotated[str, text(1, 4000)] | None, blank_as_none] = None
    image_url: Annotated[ImageUrl | None, blank_as_none] = None
    image_alt: Annotated[Annotated[str, text(1, 160)] | None, blank_as_none] = None
    image_credit: Annotated[Annotated[str, text(1, 160)] | None, blank_as_none] = None
    seo_title: Annotated[Annotated[str, text(1, 70)] | None, blank_as_none] = None
    seo_description: Annotated[Annotated[str, text(1, 160)] | None, blank_as_none] = None

    @model_validator(mode="after")
    def _something_to_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        return self
