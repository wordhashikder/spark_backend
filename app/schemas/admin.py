"""Admin request and response bodies."""

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.core.enums import (
    ChargerFollowup,
    ChargerLocation,
    ContactSubject,
    ExistingCharger,
    FuseBoxDistance,
    InstallationType,
    InstallerStatus,
    Plan,
    QuoteStatus,
    ReviewStatus,
    SubscriptionStatus,
    Timing,
)
from app.models import Installer, Review
from app.schemas.installer import Accreditation


class AdminInstaller(BaseModel):
    id: uuid.UUID
    slug: str
    business_name: str
    contact_name: str
    email: str
    phone: str
    town: str
    base_postcode: str
    location_slug: str
    status: InstallerStatus
    plan: Plan
    requested_plan: Plan | None
    is_featured: bool
    subscription_status: SubscriptionStatus
    rating_avg: float | None
    review_count: int
    accreditations: list[Accreditation]
    created_at: datetime
    approved_at: datetime | None

    @classmethod
    def from_installer(cls, installer: Installer) -> Self:
        return cls(
            id=installer.id,
            slug=installer.slug,
            business_name=installer.business_name,
            contact_name=installer.contact_name,
            email=installer.user.email,
            phone=installer.phone,
            town=installer.town,
            base_postcode=installer.base_postcode,
            location_slug=installer.location.slug,
            status=installer.status,
            plan=installer.plan,
            requested_plan=installer.requested_plan,
            is_featured=installer.is_featured,
            subscription_status=installer.subscription_status,
            rating_avg=None if installer.rating_avg is None else float(installer.rating_avg),
            review_count=installer.review_count,
            accreditations=installer.accreditations,
            created_at=installer.created_at,
            approved_at=installer.approved_at,
        )


class AdminInstallerUpdate(BaseModel):
    status: InstallerStatus | None = None
    plan: Plan | None = None
    is_featured: bool | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> Self:
        if all(getattr(self, name) is None for name in type(self).model_fields):
            raise ValueError("Provide at least one of status, plan or is_featured.")
        return self


class AccreditationVerification(BaseModel):
    verified: bool


class AdminReview(BaseModel):
    id: uuid.UUID
    installer_id: uuid.UUID
    installer_slug: str
    installer_name: str
    rating: int
    title: str
    body: str
    author_name: str
    author_location: str | None
    verified: bool
    status: ReviewStatus
    created_at: datetime
    published_at: datetime | None

    @classmethod
    def from_review(cls, review: Review) -> Self:
        return cls(
            id=review.id,
            installer_id=review.installer_id,
            installer_slug=review.installer.slug,
            installer_name=review.installer.business_name,
            rating=review.rating,
            title=review.title,
            body=review.body,
            author_name=review.author_name,
            author_location=review.author_location,
            verified=review.verified,
            status=review.status,
            created_at=review.created_at,
            published_at=review.published_at,
        )


class AdminReviewUpdate(BaseModel):
    status: ReviewStatus


class AdminQuote(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference: str
    status: QuoteStatus
    postcode: str
    district: str | None
    region: str | None
    installation_type: InstallationType
    charger_location: ChargerLocation
    existing_charger: ExistingCharger
    charger_followup: ChargerFollowup
    fuse_box_distance: FuseBoxDistance
    vehicle: str | None
    vehicle_undecided: bool
    timing: Timing
    notes: str | None
    first_name: str
    email: str
    phone: str
    target_installer_id: uuid.UUID | None
    created_at: datetime


class AdminContactMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    subject: ContactSubject
    message: str
    created_at: datetime
