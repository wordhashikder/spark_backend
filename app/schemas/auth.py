"""Authentication request and response bodies."""

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints, field_validator

from app.core.enums import InstallerStatus, Role, StaffRole, SubscriptionStatus
from app.schemas.common import Email, OpaqueToken, Password, Phone, Postcode, text
from app.schemas.plan import PlanKey

# Login accepts any string and simply fails to match: malformed input must not be
# distinguishable from a wrong password.
LoginEmail = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=1, max_length=254)
]


class RegisterRequest(BaseModel):
    email: Email
    password: Password
    business_name: Annotated[str, text(2, 120)]
    contact_name: Annotated[str, text(2, 80)]
    phone: Phone
    postcode: Postcode
    plan: PlanKey
    accept_terms: bool

    @field_validator("accept_terms")
    @classmethod
    def _terms_must_be_accepted(cls, value: bool) -> bool:
        if not value:
            raise ValueError("You must accept the terms to create an account.")
        return value


class LoginRequest(BaseModel):
    email: LoginEmail
    password: Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class EmailRequest(BaseModel):
    email: Email


class TokenRequest(BaseModel):
    token: OpaqueToken


class RefreshRequest(BaseModel):
    refresh_token: OpaqueToken


class ResetPasswordRequest(BaseModel):
    token: OpaqueToken
    password: Password


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - the OAuth2 token type, not a secret
    expires_in: int


class MeInstaller(BaseModel):
    slug: str
    business_name: str
    status: InstallerStatus
    plan: str
    plan_name: str
    subscription_status: SubscriptionStatus


class Me(BaseModel):
    id: uuid.UUID
    email: str
    role: Role
    email_verified: bool
    installer: MeInstaller | None
    full_name: str | None = None
    # Team members only: their staff role and the back-office modules it may use.
    staff_role: StaffRole | None = None
    permissions: list[str] = []


class DashboardHandoff(BaseModel):
    """Where to send a signed-in person so the Dashboard opens already signed in."""

    url: str


class AccessToken(BaseModel):
    """A session for the Dashboard app: the refresh token travels in an httpOnly cookie."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - the OAuth2 token type, not a secret
    expires_in: int
    user: Me


class ChangePasswordRequest(BaseModel):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    new_password: Password


class ClaimRequest(BaseModel):
    email: Email


class ClaimPreview(BaseModel):
    business_name: str
    slug: str
    email: str
    town: str


class ClaimAccount(BaseModel):
    token: OpaqueToken
    password: Password
    accept_terms: bool

    @field_validator("accept_terms")
    @classmethod
    def _terms_must_be_accepted(cls, value: bool) -> bool:
        if not value:
            raise ValueError("You must accept the terms to claim the listing.")
        return value
