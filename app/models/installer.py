"""Installer businesses, their accreditations and gallery photos."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    AccreditationScheme,
    InstallerSource,
    InstallerStatus,
    Plan,
    Service,
    SubscriptionStatus,
)
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.location import Location
from app.models.user import User

MIN_COVERAGE_RADIUS_MILES = 1
MAX_COVERAGE_RADIUS_MILES = 100
DEFAULT_COVERAGE_RADIUS_MILES = 15
_SERVICE_KEYS = ", ".join(f"'{service.value}'" for service in Service)


class Installer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "installers"
    __table_args__ = (
        CheckConstraint(
            f"coverage_radius_miles BETWEEN {MIN_COVERAGE_RADIUS_MILES} "
            f"AND {MAX_COVERAGE_RADIUS_MILES}",
            name="coverage_radius_range",
        ),
        CheckConstraint("years_experience IS NULL OR years_experience >= 0", name="years_positive"),
        CheckConstraint("rating_avg IS NULL OR rating_avg BETWEEN 1 AND 5", name="rating_range"),
        CheckConstraint("review_count >= 0", name="review_count_positive"),
        CheckConstraint(f"services <@ ARRAY[{_SERVICE_KEYS}]::varchar[]", name="services_known"),
        Index("ix_installers_latitude_longitude", "latitude", "longitude"),
        Index("ix_installers_status_is_featured", "status", "is_featured"),
    )

    # The account that manages the listing. Empty for a listing PickASparky added that the
    # business has not claimed yet; deleting the account leaves the listing unclaimed.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True
    )
    source: Mapped[InstallerSource] = mapped_column(
        pg_enum(InstallerSource, "installer_source"),
        default=InstallerSource.REGISTERED,
        server_default=InstallerSource.REGISTERED.value,
    )
    # Business email for listings without an account: the address a claim link is sent to.
    contact_email: Mapped[str | None] = mapped_column(String(254))
    # Street address as supplied for imported listings (never shown publicly).
    address: Mapped[str | None] = mapped_column(String(255))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    slug: Mapped[str] = mapped_column(String(140), unique=True)
    business_name: Mapped[str] = mapped_column(String(120))
    contact_name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(30))
    tagline: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    website_url: Mapped[str | None] = mapped_column(String(255))
    company_number: Mapped[str | None] = mapped_column(String(20))
    base_postcode: Mapped[str] = mapped_column(String(8))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    town: Mapped[str] = mapped_column(String(120))
    location_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("locations.id", ondelete="RESTRICT"), index=True
    )
    coverage_radius_miles: Mapped[int] = mapped_column(
        Integer,
        default=DEFAULT_COVERAGE_RADIUS_MILES,
        server_default=text(str(DEFAULT_COVERAGE_RADIUS_MILES)),
    )
    years_experience: Mapped[int | None] = mapped_column(Integer)
    logo_url: Mapped[str | None] = mapped_column(String(500))
    logo_public_id: Mapped[str | None] = mapped_column(String(255))
    services: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), default=list, server_default=text("'{}'")
    )
    areas_covered: Mapped[list[str]] = mapped_column(
        ARRAY(String(80)), default=list, server_default=text("'{}'")
    )
    status: Mapped[InstallerStatus] = mapped_column(
        pg_enum(InstallerStatus, "installer_status"),
        default=InstallerStatus.PENDING,
        server_default=InstallerStatus.PENDING.value,
    )
    plan: Mapped[Plan] = mapped_column(
        pg_enum(Plan, "plan"), default=Plan.FREE, server_default=Plan.FREE.value
    )
    requested_plan: Mapped[Plan | None] = mapped_column(pg_enum(Plan, "plan"))
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    subscription_status: Mapped[SubscriptionStatus] = mapped_column(
        pg_enum(SubscriptionStatus, "subscription_status"),
        default=SubscriptionStatus.NONE,
        server_default=SubscriptionStatus.NONE.value,
    )
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rating_avg: Mapped[Decimal | None] = mapped_column(Numeric(2, 1))
    review_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User | None] = relationship(lazy="raise")
    location: Mapped[Location] = relationship(lazy="raise")
    accreditations: Mapped[list[InstallerAccreditation]] = relationship(
        back_populates="installer",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="InstallerAccreditation.scheme",
        lazy="raise",
    )
    photos: Mapped[list[InstallerPhoto]] = relationship(
        back_populates="installer",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="InstallerPhoto.position",
        lazy="raise",
    )

    @property
    def is_claimed(self) -> bool:
        """Whether a business account manages this listing."""
        return self.user_id is not None


class InstallerAccreditation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "installer_accreditations"
    __table_args__ = (
        UniqueConstraint(
            "installer_id", "scheme", name="uq_installer_accreditations_installer_scheme"
        ),
    )

    installer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("installers.id", ondelete="CASCADE"))
    scheme: Mapped[AccreditationScheme] = mapped_column(
        pg_enum(AccreditationScheme, "accreditation_scheme")
    )
    registration_number: Mapped[str | None] = mapped_column(String(60))
    verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    installer: Mapped[Installer] = relationship(back_populates="accreditations", lazy="raise")


class InstallerPhoto(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "installer_photos"

    installer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("installers.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(String(500))
    public_id: Mapped[str | None] = mapped_column(String(255))
    alt: Mapped[str | None] = mapped_column(String(160))
    position: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    installer: Mapped[Installer] = relationship(back_populates="photos", lazy="raise")
