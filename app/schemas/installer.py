"""Installer request and response bodies, including the plan gating of public profiles."""

import re
import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from app.core.enums import AccreditationScheme, InstallerStatus, Service, SubscriptionStatus
from app.core.exceptions import FieldValueError
from app.core.plans import capabilities_for, registry
from app.models import Installer
from app.models.installer import MAX_COVERAGE_RADIUS_MILES, MIN_COVERAGE_RADIUS_MILES
from app.schemas.common import Phone, Postcode, blank_as_none, text

MAX_AREAS_COVERED = 20
_COMPANY_NUMBER = re.compile(r"[A-Z0-9]{8}")
_http_url = TypeAdapter(HttpUrl)
_REQUIRED_PROFILE_FIELDS = (
    "business_name",
    "contact_name",
    "phone",
    "base_postcode",
    "coverage_radius_miles",
    "services",
    "areas_covered",
    "accreditations",
)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _validate_website(value: str) -> str:
    try:
        return str(_http_url.validate_python(value))
    except ValidationError as exc:
        raise ValueError("Enter a web address starting with http:// or https://.") from exc


def _validate_company_number(value: str) -> str:
    if not _COMPANY_NUMBER.fullmatch(value):
        raise ValueError("Enter the 8-character Companies House number.")
    return value


CompanyNumber = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True),
    AfterValidator(_validate_company_number),
]
WebsiteUrl = Annotated[str, text(1, 255), AfterValidator(_validate_website)]


class Accreditation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scheme: AccreditationScheme
    registration_number: str | None
    verified: bool


class Photo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    alt: str | None


class Coverage(BaseModel):
    latitude: float
    longitude: float
    radius_miles: int


class CoverImage(BaseModel):
    """The town's photo, shown behind a profile that has no photos of its own."""

    url: str
    alt: str | None
    credit: str | None


class InstallerCard(BaseModel):
    slug: str
    business_name: str
    logo_url: str | None
    town: str
    location_slug: str
    rating_avg: float | None
    review_count: int
    plan: str
    is_featured: bool
    # Approved by PickASparky and run by the business's own account. Listings PickASparky
    # added and nobody has claimed yet are not shown as verified.
    verified: bool
    is_claimed: bool

    @classmethod
    def from_installer(cls, installer: Installer) -> Self:
        return cls(**_card_fields(installer))


class InstallerDetail(InstallerCard):
    tagline: str | None
    description: str | None
    years_experience: int | None
    services: list[Service]
    accreditations: list[Accreditation]
    areas_covered: list[str]
    coverage: Coverage
    photos: list[Photo]
    accepts_direct_quotes: bool
    # "M20": where the business is based, without the full postcode.
    postcode_district: str
    listed_since: datetime | None
    cover_image: CoverImage | None

    @classmethod
    def from_installer(cls, installer: Installer) -> Self:
        """Public profile with the plan's gating applied (see `core/plans.py`)."""
        plan = capabilities_for(installer.plan)
        full = plan.full_public_profile
        return cls(
            **_card_fields(installer),
            **_profile_fields(installer),
            services=installer.services[: plan.public_service_limit],
            accreditations=installer.accreditations if full else [],
            # Where the business works is basic listing information, so every plan shows it
            # (the admin's edits to it must reach the public page whatever the plan).
            areas_covered=installer.areas_covered,
            photos=installer.photos if full else [],
            # Requests to an unclaimed listing go to the team (see `services/enquiries.py`).
            accepts_direct_quotes=plan.accepts_direct_quotes and installer.is_claimed,
        )


class InstallerProfile(InstallerDetail):
    """The installer's own, ungated view of their profile and account state."""

    status: InstallerStatus
    plan_name: str
    # What the current plan allows, so the profile page can say what is and is not included.
    max_gallery_photos: int
    public_service_limit: int | None
    requested_plan: str | None
    cancel_at_period_end: bool
    subscription_status: SubscriptionStatus
    current_period_end: datetime | None
    base_postcode: str
    phone: str
    contact_name: str
    company_number: str | None
    website_url: str | None
    coverage_radius_miles: int

    @classmethod
    def from_installer(cls, installer: Installer) -> Self:
        return cls(
            **_card_fields(installer),
            **_profile_fields(installer),
            services=installer.services,
            accreditations=installer.accreditations,
            areas_covered=installer.areas_covered,
            photos=installer.photos,
            accepts_direct_quotes=capabilities_for(installer.plan).accepts_direct_quotes,
            status=installer.status,
            plan_name=registry.entry(installer.plan).name,
            max_gallery_photos=capabilities_for(installer.plan).max_gallery_photos,
            public_service_limit=capabilities_for(installer.plan).public_service_limit,
            requested_plan=installer.requested_plan,
            cancel_at_period_end=installer.cancel_at_period_end,
            subscription_status=installer.subscription_status,
            current_period_end=installer.current_period_end,
            base_postcode=installer.base_postcode,
            phone=installer.phone,
            contact_name=installer.contact_name,
            company_number=installer.company_number,
            website_url=installer.website_url,
            coverage_radius_miles=installer.coverage_radius_miles,
        )


def _card_fields(installer: Installer) -> dict[str, object]:
    return {
        "slug": installer.slug,
        "business_name": installer.business_name,
        "logo_url": installer.logo_url,
        "town": installer.town,
        "location_slug": installer.location.slug,
        "rating_avg": None if installer.rating_avg is None else float(installer.rating_avg),
        "review_count": installer.review_count,
        "plan": installer.plan,
        "is_featured": installer.is_featured,
        "verified": installer.status is InstallerStatus.APPROVED and installer.is_claimed,
        "is_claimed": installer.is_claimed,
    }


def _profile_fields(installer: Installer) -> dict[str, object]:
    return {
        "tagline": installer.tagline,
        "description": installer.description,
        "years_experience": installer.years_experience,
        "postcode_district": installer.base_postcode.split(" ")[0],
        "listed_since": installer.approved_at,
        "cover_image": (
            CoverImage(
                url=installer.location.image_url,
                alt=installer.location.image_alt,
                credit=installer.location.image_credit,
            )
            if installer.location.image_url
            else None
        ),
        "coverage": Coverage(
            latitude=installer.latitude,
            longitude=installer.longitude,
            radius_miles=installer.coverage_radius_miles,
        ),
    }


class AccreditationInput(BaseModel):
    scheme: AccreditationScheme
    registration_number: Annotated[Annotated[str, text(1, 60)] | None, blank_as_none] = None


class InstallerUpdate(BaseModel):
    """Partial profile update: only the fields present in the body are changed."""

    business_name: Annotated[str, text(2, 120)] | None = None
    contact_name: Annotated[str, text(2, 80)] | None = None
    phone: Phone | None = None
    tagline: Annotated[Annotated[str, text(1, 120)] | None, blank_as_none] = None
    description: Annotated[Annotated[str, text(1, 4000)] | None, blank_as_none] = None
    website_url: Annotated[WebsiteUrl | None, blank_as_none] = None
    company_number: Annotated[CompanyNumber | None, blank_as_none] = None
    base_postcode: Postcode | None = None
    coverage_radius_miles: int | None = Field(
        default=None, ge=MIN_COVERAGE_RADIUS_MILES, le=MAX_COVERAGE_RADIUS_MILES
    )
    years_experience: int | None = Field(default=None, ge=0, le=80)
    services: Annotated[list[Service], AfterValidator(_unique)] | None = None
    areas_covered: (
        Annotated[
            list[Annotated[str, text(1, 80)]],
            Field(max_length=MAX_AREAS_COVERED),
            AfterValidator(_unique),
        ]
        | None
    ) = None
    accreditations: list[AccreditationInput] | None = Field(
        default=None, max_length=len(AccreditationScheme)
    )

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        for name in _REQUIRED_PROFILE_FIELDS:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise FieldValueError(name, "This field cannot be empty.")
        schemes = [item.scheme for item in self.accreditations or []]
        if len(schemes) != len(set(schemes)):
            raise FieldValueError("accreditations", "Each accreditation can only be listed once.")
        return self
