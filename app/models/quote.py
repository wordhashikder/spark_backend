"""Customer quote requests and the leads they generate for installers."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    ChargerFollowup,
    ChargerLocation,
    ExistingCharger,
    FuseBoxDistance,
    InstallationType,
    LeadStatus,
    QuoteStatus,
    Timing,
)
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, pg_enum
from app.models.installer import Installer


class QuoteRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "quote_requests"
    __table_args__ = (Index("ix_quote_requests_created_at", "created_at"),)

    reference: Mapped[str] = mapped_column(String(12), unique=True)
    postcode: Mapped[str] = mapped_column(String(8))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    district: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    installation_type: Mapped[InstallationType] = mapped_column(
        pg_enum(InstallationType, "installation_type")
    )
    charger_location: Mapped[ChargerLocation] = mapped_column(
        pg_enum(ChargerLocation, "charger_location")
    )
    existing_charger: Mapped[ExistingCharger] = mapped_column(
        pg_enum(ExistingCharger, "existing_charger")
    )
    charger_followup: Mapped[ChargerFollowup] = mapped_column(
        pg_enum(ChargerFollowup, "charger_followup")
    )
    fuse_box_distance: Mapped[FuseBoxDistance] = mapped_column(
        pg_enum(FuseBoxDistance, "fuse_box_distance")
    )
    vehicle: Mapped[str | None] = mapped_column(String(120))
    vehicle_undecided: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    timing: Mapped[Timing] = mapped_column(pg_enum(Timing, "quote_timing"))
    notes: Mapped[str | None] = mapped_column(Text)
    first_name: Mapped[str] = mapped_column(String(60))
    email: Mapped[str] = mapped_column(String(254))
    # Optional: customers may choose to be contacted by email only.
    phone: Mapped[str | None] = mapped_column(String(30))
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    target_installer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("installers.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[QuoteStatus] = mapped_column(
        pg_enum(QuoteStatus, "quote_status"),
        default=QuoteStatus.NEW,
        server_default=QuoteStatus.NEW.value,
        index=True,
    )
    ip_hash: Mapped[str] = mapped_column(String(64), index=True)


class QuoteMatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A lead: one quote request offered to one installer."""

    __tablename__ = "quote_matches"
    __table_args__ = (
        UniqueConstraint(
            "quote_request_id", "installer_id", name="uq_quote_matches_quote_installer"
        ),
        Index("ix_quote_matches_installer_id_created_at", "installer_id", "created_at"),
    )

    quote_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quote_requests.id", ondelete="CASCADE")
    )
    installer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("installers.id", ondelete="CASCADE"))
    status: Mapped[LeadStatus] = mapped_column(
        pg_enum(LeadStatus, "lead_status"),
        default=LeadStatus.SENT,
        server_default=LeadStatus.SENT.value,
    )
    review_invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    quote_request: Mapped[QuoteRequest] = relationship(lazy="raise")
    installer: Mapped[Installer] = relationship(lazy="raise")
