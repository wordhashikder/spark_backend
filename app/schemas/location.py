"""Location and postcode lookup responses."""

from pydantic import BaseModel, ConfigDict


class LocationRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str


class LocationSummary(LocationRef):
    region: str
    installer_count: int


class LocationDetail(LocationSummary):
    latitude: float
    longitude: float
    intro: str | None
    image_url: str | None


class LocationDirectory(BaseModel):
    anchor: LocationRef
    nearby: list[LocationRef]
    popular: list[LocationRef]
    more_in_area: list[LocationRef]
    other: list[LocationRef]


class PostcodeLookup(BaseModel):
    postcode: str
    district: str | None
    region: str | None
    installers_in_range: int
