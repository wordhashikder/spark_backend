"""Fakes for external services and factories for arranging test data."""

import itertools
import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

import stripe
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.config import get_settings
from app.core.enums import InstallerStatus, Plan, ReviewStatus, Role
from app.models import Installer, InstallerAccreditation, Location, Review, User
from app.models.base import utcnow
from app.services.email import Email, SmtpEmailSender
from app.services.geocoding import (
    GeocodedPostcode,
    GeocodingUnavailableError,
    PostcodeNotFoundError,
)
from app.services.storage import StoredImage

PASSWORD = "Sup3rSecret-pass"
# Hashed once: Argon2 is deliberately slow and most tests only need *a* valid hash.
PASSWORD_HASH = security._password_hash.hash(PASSWORD)

MANCHESTER = (53.4808, -2.2426)
SALFORD = (53.4875, -2.2901)
STOCKPORT = (53.4106, -2.1575)
LEEDS = (53.8008, -1.5491)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
_counter = itertools.count(1)


class FakeGeocoder:
    def __init__(self) -> None:
        self.unavailable = False
        self.places = {
            "M1 1AA": GeocodedPostcode("M1 1AA", *MANCHESTER, "Manchester", "North West"),
            "SK1 3XE": GeocodedPostcode("SK1 3XE", *STOCKPORT, "Stockport", "North West"),
            "LS1 4AP": GeocodedPostcode("LS1 4AP", *LEEDS, "Leeds", "Yorkshire and the Humber"),
        }

    async def lookup(self, postcode: str) -> GeocodedPostcode:
        if self.unavailable:
            raise GeocodingUnavailableError
        if postcode not in self.places:
            raise PostcodeNotFoundError
        return self.places[postcode]


class FakeEmailSender:
    """Records emails; also renders each one so broken templates fail the test."""

    def __init__(self) -> None:
        self.sent: list[Email] = []
        self._renderer = SmtpEmailSender(get_settings())

    async def send(self, email: Email) -> None:
        self._renderer.render(email)
        self.sent.append(email)

    def of(self, template: str) -> list[Email]:
        return [email for email in self.sent if email.template == template]

    def token_from(self, template: str) -> str:
        """The `token` query parameter of the link in the latest email of this kind."""
        link = self.of(template)[-1].context["link"]
        return re.search(r"token=([^&]+)", link).group(1)


class FakeStorage:
    def __init__(self) -> None:
        self.uploaded: list[str] = []
        self.deleted: list[str] = []

    async def upload(self, data: bytes, *, folder: str) -> StoredImage:
        public_id = f"{folder}/image-{len(self.uploaded) + 1}"
        self.uploaded.append(public_id)
        return StoredImage(url=f"https://images.test/{public_id}.png", public_id=public_id)

    async def delete(self, public_id: str) -> None:
        self.deleted.append(public_id)


@dataclass
class FakeBillingGateway:
    customers: list[dict[str, str]] = field(default_factory=list)
    checkouts: list[dict[str, Any]] = field(default_factory=list)
    subscriptions: dict[str, Mapping[str, Any]] = field(default_factory=dict)

    async def create_customer(self, *, email: str, name: str, installer_id: str) -> str:
        self.customers.append({"email": email, "name": name, "installer_id": installer_id})
        return f"cus_test_{len(self.customers)}"

    async def create_checkout_session(
        self, *, customer_id: str, price_id: str, installer_id: str, plan: Plan
    ) -> str:
        self.checkouts.append(
            {"customer_id": customer_id, "price_id": price_id, "installer_id": installer_id}
        )
        return f"https://checkout.stripe.test/{plan.value}"

    async def create_portal_session(self, *, customer_id: str) -> str:
        return f"https://portal.stripe.test/{customer_id}"

    async def get_subscription(self, subscription_id: str) -> Mapping[str, Any]:
        return self.subscriptions[subscription_id]


@dataclass
class Fakes:
    STATE_NAMES: ClassVar[tuple[str, ...]] = (
        "geocoder",
        "email_sender",
        "storage",
        "billing_gateway",
    )

    geocoder: FakeGeocoder = field(default_factory=FakeGeocoder)
    emails: FakeEmailSender = field(default_factory=FakeEmailSender)
    storage: FakeStorage = field(default_factory=FakeStorage)
    billing: FakeBillingGateway = field(default_factory=FakeBillingGateway)

    def install(self, app: FastAPI) -> None:
        app.state.geocoder = self.geocoder
        app.state.email_sender = self.emails
        app.state.storage = self.storage
        app.state.billing_gateway = self.billing


def auth_headers(user: User) -> dict[str, str]:
    token, _ = security.create_access_token(user.id, user.role)
    return {"Authorization": f"Bearer {token}"}


async def create_user(
    db: AsyncSession,
    *,
    email: str | None = None,
    role: Role = Role.INSTALLER,
    verified: bool = True,
    active: bool = True,
) -> User:
    user = User(
        email=email or f"user{next(_counter)}@example.com",
        password_hash=PASSWORD_HASH,
        role=role,
        is_active=active,
        email_verified_at=utcnow() if verified else None,
    )
    db.add(user)
    await db.commit()
    return user


async def create_installer(
    db: AsyncSession,
    name: str,
    *,
    at: tuple[float, float] = MANCHESTER,
    location: str = "manchester",
    plan: Plan = Plan.PRO,
    status: InstallerStatus = InstallerStatus.APPROVED,
    radius: int = 15,
    featured: bool = False,
    rating: float | None = None,
    review_count: int = 0,
    services: tuple[str, ...] = ("ev_charger_installation", "domestic_electrical", "smart_home"),
    accreditations: tuple[str, ...] = ("ozev",),
) -> Installer:
    """Insert an installer (with its own user) and return it with `user` and `location` loaded."""
    place = await db.scalar(select(Location).where(Location.slug == location))
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    installer = Installer(
        user=User(
            email=f"{slug}@example.com",
            password_hash=PASSWORD_HASH,
            role=Role.INSTALLER,
            email_verified_at=utcnow(),
        ),
        slug=slug,
        business_name=name,
        contact_name="Alex Installer",
        phone="0161 496 0000",
        tagline="Chargers fitted properly",
        description="We fit chargers.",
        base_postcode="M1 1AA",
        latitude=at[0],
        longitude=at[1],
        town=place.name,
        location=place,
        coverage_radius_miles=radius,
        services=list(services),
        areas_covered=["Manchester", "Salford"],
        status=status,
        plan=plan,
        is_featured=featured,
        rating_avg=rating,
        review_count=review_count,
        accreditations=[
            InstallerAccreditation(scheme=scheme, registration_number="REG-1", verified=True)
            for scheme in accreditations
        ],
        photos=[],
    )
    db.add(installer)
    await db.commit()
    return installer


async def create_review(
    db: AsyncSession,
    installer: Installer,
    *,
    rating: int = 5,
    status: ReviewStatus = ReviewStatus.PUBLISHED,
    title: str = "Great service",
) -> Review:
    review = Review(
        installer_id=installer.id,
        rating=rating,
        title=title,
        body="They turned up on time and did a tidy job.",
        author_name="Steve M.",
        author_location="Manchester",
        status=status,
        published_at=utcnow() if status is ReviewStatus.PUBLISHED else None,
    )
    db.add(review)
    await db.commit()
    return review


def quote_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "postcode": "m1 1aa",
        "installation_type": "new_home",
        "charger_location": "house_wall",
        "existing_charger": "no",
        "charger_followup": "installer_recommend",
        "fuse_box_distance": "under_10m",
        "vehicle": "Tesla Model Y",
        "vehicle_undecided": False,
        "timing": "within_month",
        "notes": "Detached garage at the back.",
        "first_name": "Sam",
        "email": "sam@example.com",
        "phone": "07700 900123",
        "consent": True,
    }
    return payload | overrides


def signed_stripe_event(
    event_type: str, data_object: Mapping[str, Any], event_id: str | None = None
) -> tuple[bytes, dict[str, str]]:
    """A webhook body and headers signed with the SDK's own helper and the test secret."""
    body = json.dumps(
        {
            "id": event_id or f"evt_test_{next(_counter)}",
            "object": "event",
            "type": event_type,
            "created": int(time.time()),
            "data": {"object": data_object},
        }
    )
    signature = stripe.WebhookSignature.generate_signature_header(
        payload=body, secret=get_settings().stripe_webhook_secret
    )
    return body.encode(), {"Stripe-Signature": signature, "Content-Type": "application/json"}


def subscription_object(
    installer: Installer, *, status: str, price_id: str, subscription_id: str = "sub_test_1"
) -> dict[str, Any]:
    return {
        "id": subscription_id,
        "object": "subscription",
        "customer": installer.stripe_customer_id or "cus_test_1",
        "status": status,
        "metadata": {"installer_id": str(installer.id)},
        "items": {
            "object": "list",
            "data": [
                {"id": "si_test_1", "price": {"id": price_id}, "current_period_end": 1_800_000_000}
            ],
        },
    }
