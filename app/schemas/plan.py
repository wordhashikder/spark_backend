"""Membership plans: the public catalogue and the Dashboard's plan manager."""

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.plans import PlanEntry
from app.models import Plan, PlanPrice
from app.schemas.common import blank_as_none, text

# A short, URL- and CSS-safe identifier. It is permanent: installers and Stripe refer to it.
PlanKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,38}[a-z0-9]$")]
Feature = Annotated[str, text(1, 200)]

MIN_PRICE_PENCE = 100
MAX_PRICE_PENCE = 1_000_000


class PublicPlan(BaseModel):
    """What the website, sign-up and upgrade screens show for a plan."""

    key: str
    name: str
    tagline: str | None
    features: list[str]
    is_popular: bool
    is_default: bool
    price_pence: int | None
    currency: str
    sort_rank: int

    @classmethod
    def from_entry(cls, entry: PlanEntry) -> Self:
        return cls(
            key=entry.key,
            name=entry.name,
            tagline=entry.tagline,
            features=list(entry.features),
            is_popular=entry.is_popular,
            is_default=entry.is_default,
            price_pence=entry.price_pence,
            currency=entry.currency,
            sort_rank=entry.capabilities.sort_rank,
        )


class PlanChoice(BaseModel):
    """A plan the team may give an installer (archived and unpriced ones included)."""

    key: str
    name: str
    is_active: bool
    is_default: bool


class PlanFields(BaseModel):
    name: Annotated[str, text(1, 60)]
    tagline: Annotated[Annotated[str, text(1, 200)] | None, blank_as_none] = None
    features: list[Feature] = Field(default_factory=list, max_length=12)
    is_active: bool = True
    is_popular: bool = False
    sort_rank: int = Field(default=0, ge=0, le=1000)
    receives_leads: bool = False
    accepts_direct_quotes: bool = False
    full_public_profile: bool = False
    # Blank = every service is shown publicly.
    public_service_limit: int | None = Field(default=None, ge=1, le=20)
    max_gallery_photos: int = Field(default=0, ge=0, le=100)


class PlanCreate(PlanFields):
    key: PlanKey
    # Monthly price in pence. Blank = a plan that cannot be bought (an admin can still assign it).
    price_pence: int | None = Field(default=None, ge=MIN_PRICE_PENCE, le=MAX_PRICE_PENCE)


class PlanUpdate(BaseModel):
    """Only the fields sent are changed. `price_pence: null` removes the price."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, text(1, 60)] | None = None
    tagline: Annotated[Annotated[str, text(1, 200)] | None, blank_as_none] = None
    features: list[Feature] | None = Field(default=None, max_length=12)
    is_active: bool | None = None
    is_popular: bool | None = None
    sort_rank: int | None = Field(default=None, ge=0, le=1000)
    receives_leads: bool | None = None
    accepts_direct_quotes: bool | None = None
    full_public_profile: bool | None = None
    public_service_limit: int | None = Field(default=None, ge=1, le=20)
    max_gallery_photos: int | None = Field(default=None, ge=0, le=100)
    price_pence: int | None = Field(default=None, ge=MIN_PRICE_PENCE, le=MAX_PRICE_PENCE)

    @model_validator(mode="after")
    def _non_nullable_fields_are_not_null(self) -> Self:
        for field in (
            "name",
            "features",
            "is_active",
            "is_popular",
            "sort_rank",
            "receives_leads",
            "accepts_direct_quotes",
            "full_public_profile",
            "max_gallery_photos",
        ):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be empty.")
        return self


class PlanPriceOut(BaseModel):
    amount_pence: int
    currency: str
    is_active: bool
    stripe_price_id: str | None
    created_at: datetime

    @classmethod
    def from_price(cls, price: PlanPrice) -> Self:
        return cls(
            amount_pence=price.amount_pence,
            currency=price.currency,
            is_active=price.is_active,
            stripe_price_id=price.stripe_price_id,
            created_at=price.created_at,
        )


class AdminPlan(BaseModel):
    key: str
    name: str
    tagline: str | None
    features: list[str]
    is_default: bool
    is_active: bool
    is_popular: bool
    sort_rank: int
    receives_leads: bool
    accepts_direct_quotes: bool
    full_public_profile: bool
    public_service_limit: int | None
    max_gallery_photos: int
    # The price new subscribers pay (monthly), and every price the plan has had.
    price_pence: int | None
    currency: str
    prices: list[PlanPriceOut]
    stripe_product_id: str | None
    stripe_price_id: str | None
    # False while the plan or its price still has to be created in Stripe.
    stripe_synced: bool
    installers: int
    subscriptions: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_plan(cls, plan: Plan, *, installers: int = 0, subscriptions: int = 0) -> Self:
        prices = sorted(plan.prices, key=lambda price: price.created_at, reverse=True)
        current = next((price for price in prices if price.is_active), None)
        return cls(
            key=plan.key,
            name=plan.name,
            tagline=plan.tagline,
            features=list(plan.features),
            is_default=plan.is_default,
            is_active=plan.is_active,
            is_popular=plan.is_popular,
            sort_rank=plan.sort_rank,
            receives_leads=plan.receives_leads,
            accepts_direct_quotes=plan.accepts_direct_quotes,
            full_public_profile=plan.full_public_profile,
            public_service_limit=plan.public_service_limit,
            max_gallery_photos=plan.max_gallery_photos,
            price_pence=current.amount_pence if current else None,
            currency=current.currency if current else "gbp",
            prices=[PlanPriceOut.from_price(price) for price in prices],
            stripe_product_id=plan.stripe_product_id,
            stripe_price_id=current.stripe_price_id if current else None,
            stripe_synced=current is None or current.stripe_price_id is not None,
            installers=installers,
            subscriptions=subscriptions,
            created_at=plan.created_at,
            updated_at=plan.updated_at,
        )
