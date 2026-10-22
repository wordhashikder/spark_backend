"""Membership plans and their prices: the catalogue the Dashboard manages."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    false,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.plans import DEFAULT_PLAN_KEY
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Plan(TimestampMixin, Base):
    """A membership tier. The `key` is permanent; everything else can be edited.

    Exactly one plan is the *default* (the free plan every account starts on and falls back
    to). It has no price and cannot be archived or deleted.
    """

    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint("sort_rank >= 0", name="sort_rank_range"),
        CheckConstraint("max_gallery_photos >= 0", name="max_gallery_photos_range"),
        CheckConstraint(
            "public_service_limit IS NULL OR public_service_limit >= 1",
            name="public_service_limit_range",
        ),
        # Only one default plan.
        Index(
            "uq_plans_single_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    tagline: Mapped[str | None] = mapped_column(String(200))
    features: Mapped[list[str]] = mapped_column(
        ARRAY(String(200)), default=list, server_default=text("'{}'")
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Archived plans cannot be chosen any more; installers already on one keep it.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    is_popular: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # Tier order: lists the plans, ranks installers in search, and decides whether a change
    # is an upgrade (higher rank) or a downgrade.
    sort_rank: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    # What the plan allows.
    receives_leads: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    accepts_direct_quotes: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    full_public_profile: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    public_service_limit: Mapped[int | None] = mapped_column(Integer)
    max_gallery_photos: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    stripe_product_id: Mapped[str | None] = mapped_column(String(255), unique=True)

    prices: Mapped[list[PlanPrice]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )


class PlanPrice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A recurring price for a plan.

    Stripe prices cannot be edited, so changing an amount retires the current row and adds a
    new one. Retired rows are kept: subscribers who signed up at the old price keep paying
    it, and the webhook still finds their plan through the old Stripe price id.
    """

    __tablename__ = "plan_prices"
    __table_args__ = (
        CheckConstraint("amount_pence > 0", name="amount_positive"),
        CheckConstraint("interval IN ('month', 'year')", name="interval_known"),
        Index(
            "uq_plan_prices_one_active",
            "plan_key",
            "interval",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    plan_key: Mapped[str] = mapped_column(ForeignKey("plans.key", ondelete="CASCADE"), index=True)
    interval: Mapped[str] = mapped_column(String(10), default="month", server_default="month")
    amount_pence: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="gbp", server_default="gbp")
    stripe_price_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    plan: Mapped[Plan] = relationship(back_populates="prices", lazy="raise")


__all__ = ["DEFAULT_PLAN_KEY", "Plan", "PlanPrice"]
