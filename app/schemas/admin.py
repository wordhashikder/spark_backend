"""Admin request and response bodies."""

import uuid
from datetime import date, datetime
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from app.core.enums import (
    AccreditationScheme,
    ChargerFollowup,
    ChargerLocation,
    ContactSubject,
    ExistingCharger,
    FuseBoxDistance,
    InstallationType,
    InstallerSource,
    InstallerStatus,
    LeadStatus,
    QuoteStatus,
    ReviewStatus,
    Service,
    SubscriptionStatus,
    Timing,
)
from app.core.exceptions import FieldValueError
from app.core.plans import DEFAULT_PLAN_KEY, registry
from app.models import Installer, QuoteMatch, Review
from app.models.installer import (
    DEFAULT_COVERAGE_RADIUS_MILES,
    MAX_COVERAGE_RADIUS_MILES,
    MIN_COVERAGE_RADIUS_MILES,
)
from app.schemas.common import Email, Phone, Postcode, blank_as_none, text
from app.schemas.installer import (
    MAX_AREAS_COVERED,
    Accreditation,
    AccreditationInput,
    CompanyNumber,
    Photo,
    WebsiteUrl,
    _unique,
)
from app.schemas.plan import PlanKey
from app.services.platform import PlatformSettings


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
    plan: str
    plan_name: str
    requested_plan: str | None
    cancel_at_period_end: bool
    pending_plan: str | None
    current_period_end: datetime | None
    is_featured: bool
    subscription_status: SubscriptionStatus
    rating_avg: float | None
    review_count: int
    accreditations: list[Accreditation]
    created_at: datetime
    approved_at: datetime | None
    description: str | None = None
    services: list[str] = []
    coverage_radius_miles: int = 15
    tagline: str | None = None
    website_url: str | None = None
    company_number: str | None = None
    years_experience: int | None = None
    areas_covered: list[str] = []
    logo_url: str | None = None
    photos: list[Photo] = []

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
            plan_name=registry.entry(installer.plan).name,
            requested_plan=installer.requested_plan,
            cancel_at_period_end=installer.cancel_at_period_end,
            pending_plan=installer.pending_plan,
            current_period_end=installer.current_period_end,
            is_featured=installer.is_featured,
            subscription_status=installer.subscription_status,
            rating_avg=None if installer.rating_avg is None else float(installer.rating_avg),
            review_count=installer.review_count,
            accreditations=installer.accreditations,
            created_at=installer.created_at,
            approved_at=installer.approved_at,
            description=installer.description,
            services=list(installer.services),
            coverage_radius_miles=installer.coverage_radius_miles,
            tagline=installer.tagline,
            website_url=installer.website_url,
            company_number=installer.company_number,
            years_experience=installer.years_experience,
            areas_covered=list(installer.areas_covered),
            logo_url=installer.logo_url,
            photos=sorted(installer.photos, key=lambda photo: photo.position),
        )


_REQUIRED_WHEN_SENT = (
    "status",
    "plan",
    "is_featured",
    "business_name",
    "phone",
    "base_postcode",
    "coverage_radius_miles",
    "services",
    "areas_covered",
    "accreditations",
)


class AdminInstallerUpdate(BaseModel):
    """Partial update by the team; only the fields sent change."""

    status: InstallerStatus | None = None
    plan: PlanKey | None = None
    is_featured: bool | None = None
    # The business email a listing can be claimed with; `null` clears it.
    contact_email: Annotated[Email | None, blank_as_none] = None
    business_name: Annotated[str, text(2, 120)] | None = None
    contact_name: Annotated[Annotated[str, text(2, 80)] | None, blank_as_none] = None
    phone: Phone | None = None
    description: Annotated[Annotated[str, text(1, 4000)] | None, blank_as_none] = None
    base_postcode: Postcode | None = None
    coverage_radius_miles: int | None = Field(
        default=None, ge=MIN_COVERAGE_RADIUS_MILES, le=MAX_COVERAGE_RADIUS_MILES
    )
    tagline: Annotated[Annotated[str, text(1, 120)] | None, blank_as_none] = None
    website_url: Annotated[WebsiteUrl | None, blank_as_none] = None
    company_number: Annotated[CompanyNumber | None, blank_as_none] = None
    years_experience: int | None = Field(default=None, ge=0, le=80)
    services: Annotated[list[Service], AfterValidator(_unique), Field(min_length=1)] | None = None
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
    def _something_to_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        for name in _REQUIRED_WHEN_SENT:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise FieldValueError(name, "This field cannot be empty.")
        schemes = [item.scheme for item in self.accreditations or []]
        if len(schemes) != len(set(schemes)):
            raise FieldValueError("accreditations", "Each accreditation can only be listed once.")
        return self


class AdminInstallerCreate(BaseModel):
    """A listing added by the team (Add installer). It has no account until claimed."""

    business_name: Annotated[str, text(2, 120)]
    contact_name: Annotated[Annotated[str, text(2, 80)] | None, blank_as_none] = None
    contact_email: Email
    phone: Phone
    description: Annotated[Annotated[str, text(1, 4000)] | None, blank_as_none] = None
    accreditations: list[AccreditationScheme] = Field(default_factory=list, max_length=6)
    services: list[Service] = Field(
        default_factory=lambda: [Service.EV_CHARGER_INSTALLATION], min_length=1
    )
    base_postcode: Postcode
    coverage_radius_miles: int = Field(
        default=DEFAULT_COVERAGE_RADIUS_MILES,
        ge=MIN_COVERAGE_RADIUS_MILES,
        le=MAX_COVERAGE_RADIUS_MILES,
    )
    status: InstallerStatus = InstallerStatus.APPROVED
    plan: PlanKey = DEFAULT_PLAN_KEY


class ImportRowError(BaseModel):
    row: int
    business_name: str | None
    message: str


class ImportReport(BaseModel):
    dry_run: bool
    rows: int
    created: int
    skipped: list[ImportRowError]
    errors: list[ImportRowError]


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
    """Moderate or edit a review; only the fields sent change."""

    status: ReviewStatus | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    title: Annotated[str, text(3, 80)] | None = None
    body: Annotated[str, text(10, 1500)] | None = None
    author_name: Annotated[str, text(2, 60)] | None = None
    author_location: Annotated[Annotated[str, text(1, 60)] | None, blank_as_none] = None
    installer_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        for name in ("status", "rating", "title", "body", "author_name", "installer_id"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise FieldValueError(name, "This field cannot be empty.")
        return self


class AdminReviewCreate(BaseModel):
    """A review added by the team (for example one received by phone or email)."""

    installer_id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    title: Annotated[str, text(3, 80)]
    body: Annotated[str, text(10, 1500)]
    author_name: Annotated[str, text(2, 60)]
    author_location: Annotated[Annotated[str, text(1, 60)] | None, blank_as_none] = None
    status: ReviewStatus = ReviewStatus.PUBLISHED


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
    # Progress (see `services/lead_stats.py`).
    stage: str = "open"
    installers_matched: int = 0
    quotes_sent: int = 0
    # The most installers a request goes to (Settings), for "3 of 5".
    max_installers: int = 5


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


class Kpi(BaseModel):
    value: float
    # Change against the previous period, in percent; null when there is nothing to compare.
    change: float | None
    hint: str


class MonthlyPoint(BaseModel):
    month: date
    leads: int
    quotes: int


class RecentLead(BaseModel):
    id: uuid.UUID
    reference: str
    first_name: str
    installation_type: InstallationType
    postcode: str
    district: str | None
    created_at: datetime
    installers_matched: int
    quotes_sent: int
    max_installers: int
    stage: str


class AdminOverview(BaseModel):
    period_days: int
    leads: Kpi
    active_installers: Kpi
    quotes_sent: Kpi
    match_rate: Kpi
    monthly: list[MonthlyPoint]
    leads_by_area: list[CountByKey]
    recent_leads: list[RecentLead]
    # Things waiting for the team.
    held_leads: int
    unmatched_leads: int
    installers_pending: int
    reviews_pending: int
    enquiries_for_team: int
    contact_messages_recent: int


class NavCounts(BaseModel):
    """Badges in the Dashboard's sidebar (only for modules the member may use)."""

    leads: int | None = None
    installers: int | None = None
    reviews: int | None = None
    inbox: int | None = None


class SearchHit(BaseModel):
    kind: str  # installer | lead | location | conversation
    id: str
    title: str
    subtitle: str
    # Dashboard route to open the hit.
    href: str


class SearchResults(BaseModel):
    query: str
    hits: list[SearchHit]


class PlatformStatus(BaseModel):
    """Configuration status for the Settings page. Never includes secrets."""

    environment: str
    frontend_url: str
    dashboard_url: str
    email_configured: bool
    image_uploads_configured: bool
    payments_configured: bool
    sms_configured: bool
    showcase_enabled: bool


class QuoteCandidate(BaseModel):
    """An installer the team could send a quote request to."""

    id: uuid.UUID
    slug: str
    business_name: str
    town: str
    plan: str
    plan_name: str
    rating_avg: float | None
    review_count: int
    # Null when the request's postcode could not be located.
    distance_miles: float | None
    covers_address: bool
    already_matched: bool


class QuoteAssign(BaseModel):
    installer_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)


class StageCounts(BaseModel):
    all: int
    open: int
    awaiting: int
    closed: int
    # Waiting for the team to choose installers (automatic matching off).
    held: int


class TeamMessageCreate(BaseModel):
    body: Annotated[str, text(1, 4000)]


class AdminSettings(BaseModel):
    """The Settings page: editable platform settings and the server's configuration."""

    settings: PlatformSettings
    status: PlatformStatus


class MediaUpload(BaseModel):
    """An image uploaded for page content (hero images, cards...)."""

    url: str


class AdminCustomer(BaseModel):
    """A homeowner's customer record, with how much they have done."""

    id: uuid.UUID
    email: str
    first_name: str
    phone: str | None
    created_at: datetime
    last_login_at: datetime | None
    requests: int
    conversations: int
    quotes_received: int
