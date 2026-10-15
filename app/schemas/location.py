"""Location and postcode lookup responses, and the admin's location content edits."""

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.core.enums import DirectoryColumn
from app.core.exceptions import FieldValueError
from app.schemas.common import ImageUrl, Postcode, blank_as_none, text

# The page's main text (Markdown): enough room for a full local guide.
INTRO_MAX_LENGTH = 20000


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
    # Heading override; null means "EV Charger Installers in {name}".
    h1_heading: str | None = None
    # The page's own block between the reviews and the directory (Markdown); null shows
    # the template's block, if the team wrote one.
    extra_title: str | None = None
    extra_body: str | None = None
    updated_at: datetime | None = None


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
    h1_heading: str | None = None
    extra_title: str | None = None
    extra_body: str | None = None
    is_published: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None
    installer_count: int = 0


class AdminLocationCreate(BaseModel):
    """A new town page (SEO & Locations → New page)."""

    name: Annotated[str, text(2, 80)]
    # A postcode near the centre of the town: places the page on the map.
    postcode: Postcode
    region: Annotated[Annotated[str, text(2, 80)] | None, blank_as_none] = None
    # Defaults to the name in lowercase with hyphens.
    slug: Annotated[Annotated[str, text(2, 80)] | None, blank_as_none] = None
    is_published: bool = False


class AdminLocationUpdate(BaseModel):
    """Partial update: only the fields sent are changed; send `null` to clear one."""

    name: Annotated[str, text(2, 80)] | None = None
    region: Annotated[str, text(2, 80)] | None = None
    slug: Annotated[str, text(2, 80)] | None = None
    is_published: bool | None = None
    h1_heading: Annotated[Annotated[str, text(1, 120)] | None, blank_as_none] = None
    intro: Annotated[Annotated[str, text(1, INTRO_MAX_LENGTH)] | None, blank_as_none] = None
    extra_title: Annotated[Annotated[str, text(1, 120)] | None, blank_as_none] = None
    extra_body: Annotated[Annotated[str, text(1, INTRO_MAX_LENGTH)] | None, blank_as_none] = None
    image_url: Annotated[ImageUrl | None, blank_as_none] = None
    image_alt: Annotated[Annotated[str, text(1, 160)] | None, blank_as_none] = None
    image_credit: Annotated[Annotated[str, text(1, 160)] | None, blank_as_none] = None
    seo_title: Annotated[Annotated[str, text(1, 70)] | None, blank_as_none] = None
    seo_description: Annotated[Annotated[str, text(1, 160)] | None, blank_as_none] = None

    @model_validator(mode="after")
    def _something_to_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        for name in ("name", "region", "slug", "is_published"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise FieldValueError(name, "This field cannot be empty.")
        return self
