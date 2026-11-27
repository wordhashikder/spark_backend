"""
Website pages the team builds: the public page, its listing in the sitemap, and the admin's
create/update requests.
"""

import re
import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.content.fields import _is_image_source, _is_safe_link
from app.core.exceptions import FieldValueError
from app.schemas.common import blank_as_none, text

MAX_SECTIONS = 30
MAX_SECTION_CARDS = 12
MAX_FAQ = 30
MAX_DEPTH = 5

_SEGMENT = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_PATH = re.compile(rf"^/(?:{_SEGMENT}/)+$")
# The target of every `](target)`, and of every image `![alt](target)`.
_TARGET = re.compile(r"\]\(\s*<?([^)\s>]+)")
_IMAGE_TARGET = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)")


def normalise_path(value: str) -> str:
    """`uk/Cost` and `/uk/cost` both become `/uk/cost/`: lower case, one slash each side."""
    cleaned = "/" + "/".join(part for part in value.strip().lower().split("/") if part) + "/"
    return cleaned


def _valid_path(value: str) -> str:
    path = normalise_path(value)
    if not _PATH.fullmatch(path) or path.count("/") - 1 > MAX_DEPTH or len(path) > 200:
        raise ValueError(
            "Use lower-case letters, numbers and single hyphens, with slashes between the "
            "parts (e.g. /uk/home-ev-charger-installation/cost/)."
        )
    return path


def _image(value: str) -> str:
    if not _is_image_source(value):
        raise ValueError("Upload the image in the Dashboard (or use a path starting with /).")
    return value


def _markdown(value: str) -> str:
    if not all(_is_image_source(target) for target in _IMAGE_TARGET.findall(value)):
        raise ValueError("Images must be uploaded in the Dashboard (Insert image).")
    if not all(_is_safe_link(target) for target in _TARGET.findall(value)):
        raise ValueError("Links must go to a site path (/page/), an https:// address or mailto:.")
    return value


PagePath = Annotated[str, AfterValidator(_valid_path)]
OptionalPath = Annotated[PagePath | None, blank_as_none]
Image = Annotated[str, Field(max_length=500), AfterValidator(_image)]
OptionalImage = Annotated[Image | None, blank_as_none]
AltText = Annotated[Annotated[str, text(1, 160)] | None, blank_as_none]
Title = Annotated[str, text(2, 120)]
Eyebrow = Annotated[Annotated[str, text(1, 60)] | None, blank_as_none]
Intro = Annotated[Annotated[str, text(1, 600)] | None, blank_as_none]
SeoTitle = Annotated[Annotated[str, text(1, 70)] | None, blank_as_none]
SeoDescription = Annotated[Annotated[str, text(1, 160)] | None, blank_as_none]


class SectionCard(BaseModel):
    """One card of a section's grid: an icon, a title and a short description."""

    # The name of an icon from the Dashboard's list. The website shows a default one for a name
    # it does not know, so an old card never breaks when the list changes.
    icon: Annotated[Annotated[str, Field(pattern=r"^[a-z0-9-]{1,40}$")] | None, blank_as_none] = (
        None
    )
    title: Annotated[str, text(1, 80)]
    description: Annotated[str, text(1, 400)]


class PageSection(BaseModel):
    heading: Annotated[str, text(1, 120)]
    # Optional when the section is made of cards.
    body: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=20_000), AfterValidator(_markdown)
    ] = ""
    image_url: OptionalImage = None
    image_alt: AltText = None
    # A grid of cards after the text (two columns on a wide screen).
    cards: Annotated[list[SectionCard], Field(max_length=MAX_SECTION_CARDS)] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def _has_content(self) -> Self:
        if not self.body and not self.cards:
            raise FieldValueError("body", "Write some text or add at least one card.")
        return self

    @model_validator(mode="after")
    def _image_needs_alt(self) -> Self:
        if self.image_url and not self.image_alt:
            raise FieldValueError("image_alt", "Describe the image for people who cannot see it.")
        return self


class PageFaq(BaseModel):
    question: Annotated[str, text(1, 200)]
    answer: Annotated[str, text(1, 2000), AfterValidator(_markdown)]


class PageRef(BaseModel):
    path: str
    title: str


class PageCard(BaseModel):
    """A supporting page, as listed on its main page."""

    model_config = ConfigDict(from_attributes=True)

    path: str
    title: str
    intro: str | None
    hero_image_url: str | None
    hero_image_alt: str | None


class PageDetail(BaseModel):
    """A page as the website shows it."""

    model_config = ConfigDict(from_attributes=True)

    path: str
    title: str
    eyebrow: str | None
    intro: str | None
    hero_image_url: str | None
    hero_image_alt: str | None
    sections: list[PageSection]
    faq: list[PageFaq]
    seo_title: str | None
    seo_description: str | None
    updated_at: AwareDatetime
    # Search engines are only asked to index a published page that has content.
    indexable: bool
    # The main page this one supports (for the "back" link), and the supporting pages it has.
    parent: PageRef | None = None
    children: list[PageCard] = Field(default_factory=list)
    # True when this view is the team's preview of an unpublished page.
    preview: bool = False


class PageLookup(BaseModel):
    """Either the page, or where it moved to (the website answers with a permanent redirect)."""

    page: PageDetail | None = None
    redirect_to: str | None = None


class PageSitemapEntry(BaseModel):
    path: str
    updated_at: datetime


class AdminPage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    path: str
    parent_path: str | None
    parent_title: str | None = None
    previous_paths: list[str]
    title: str
    eyebrow: str | None
    intro: str | None
    hero_image_url: str | None
    hero_image_alt: str | None
    sections: list[PageSection]
    faq: list[PageFaq]
    seo_title: str | None
    seo_description: str | None
    is_published: bool
    scheme_key: str | None
    has_content: bool
    is_indexable: bool
    child_count: int = 0
    created_at: datetime
    updated_at: datetime


class PageCreate(BaseModel):
    title: Title
    path: PagePath
    parent_path: OptionalPath = None
    is_published: bool = False


class PageUpdate(BaseModel):
    """Partial update: only the fields present in the body are changed."""

    title: Title | None = None
    path: PagePath | None = None
    parent_path: OptionalPath = None
    eyebrow: Eyebrow = None
    intro: Intro = None
    hero_image_url: OptionalImage = None
    hero_image_alt: AltText = None
    sections: Annotated[list[PageSection], Field(max_length=MAX_SECTIONS)] | None = None
    faq: Annotated[list[PageFaq], Field(max_length=MAX_FAQ)] | None = None
    seo_title: SeoTitle = None
    seo_description: SeoDescription = None
    is_published: bool | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        for name in ("title", "path", "sections", "faq", "is_published"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise FieldValueError(name, "This field cannot be empty.")
        return self


class PagePreview(BaseModel):
    token: str
    expires_in: int
