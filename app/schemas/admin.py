"""Admin request and response bodies."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.core.enums import (
    ChargerFollowup,
    ChargerLocation,
    ContactSubject,
    ExistingCharger,
    FuseBoxDistance,
    InstallationType,
    InstallerSource,
    InstallerStatus,
    LeadStatus,
    Plan,
    QuoteStatus,
    ReviewStatus,
    Role,
    SubscriptionStatus,
    Timing,
)
from app.models import Installer, QuoteMatch, Review
from app.schemas.common import Email, blank_as_none
from app.schemas.installer import Accreditation


class AdminInstaller(BaseModel):
    id: uuid.UUID
    slug: str
    business_name: str
    contact_name: str
    # The account's email, or the business email held for an unclaimed listing.
    email: str | None
    phone: str
    source: InstallerSource
    is_claimed: bool
    claimed_at: datetime | None
    address: str | None
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
            email=installer.user.email if installer.user else installer.contact_email,
            phone=installer.phone,
            source=installer.source,
            is_claimed=installer.is_claimed,
            claimed_at=installer.claimed_at,
            address=installer.address,
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
    # The business email a listing can be claimed with; `null` clears it.
    contact_email: Annotated[Email | None, blank_as_none] = None

    @model_validator(mode="after")
    def _something_to_change(self) -> Self:
        if not self.model_fields_set or (
            "contact_email" not in self.model_fields_set
            and all(getattr(self, name) is None for name in ("status", "plan", "is_featured"))
        ):
            raise ValueError("Provide at least one of status, plan, is_featured or contact_email.")
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
    phone: str | None
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


class AdminQuoteMatch(BaseModel):
    """One installer a quote request was sent to."""

    id: uuid.UUID
    installer_id: uuid.UUID
    installer_slug: str
    installer_name: str
    status: LeadStatus
    created_at: datetime

    @classmethod
    def from_match(cls, match: QuoteMatch) -> Self:
        return cls(
            id=match.id,
            installer_id=match.installer_id,
            installer_slug=match.installer.slug,
            installer_name=match.installer.business_name,
            status=match.status,
            created_at=match.created_at,
        )


class CountByKey(BaseModel):
    key: str
    count: int


class DailyCount(BaseModel):
    day: date
    count: int


class AdminOverview(BaseModel):
    period_days: int
    installers_total: int
    installers_by_status: list[CountByKey]
    installers_by_plan: list[CountByKey]
    installers_by_source: list[CountByKey]
    installers_claimed: int
    installers_pending: int
    quote_requests_total: int
    quote_requests_recent: int
    quote_requests_by_status: list[CountByKey]
    leads_total: int
    enquiries_total: int
    enquiries_recent: int
    enquiries_for_team: int
    conversations_total: int
    offers_by_status: list[CountByKey]
    accepted_quote_value: Decimal
    reviews_pending: int
    reviews_published: int
    contact_messages_recent: int
    blog_published: int
    blog_drafts: int
    locations_total: int
    quote_requests_daily: list[DailyCount]
    enquiries_daily: list[DailyCount]


class Permission(BaseModel):
    key: str
    area: str
    label: str
    roles: list[Role]


class RoleInfo(BaseModel):
    role: Role
    label: str
    description: str


class RoleMatrix(BaseModel):
    roles: list[RoleInfo]
    permissions: list[Permission]


class PlatformInfo(BaseModel):
    environment: str
    frontend_url: str
    dashboard_url: str
    support_email: str
    email_configured: bool
    image_uploads_configured: bool
    payments_configured: bool
    max_quote_matches: int
    showcase_enabled: bool
    admins: list[str]
