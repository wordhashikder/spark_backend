"""Claiming a listing: a business takes over the free listing created for it.

Imported listings have no account. The business proves it owns a listing by following a
link sent to the email address on file for it (`installers.contact_email`), then sets a
password. The new account is verified (the mailbox was proved) and linked to the listing.
Claiming changes nothing public: the listing stays on the Free plan until it upgrades.
"""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core import security
from app.core.enums import InstallerStatus, Role
from app.core.exceptions import ConflictError, InvalidTokenError, NotFoundError
from app.models import Installer, User
from app.models.base import utcnow
from app.services import email as emails
from app.services.email import Email

logger = logging.getLogger(__name__)


class ListingAlreadyClaimedError(ConflictError):
    code = "listing_already_claimed"
    message = "This listing has already been claimed. Sign in, or reset your password."


class EmailInUseError(ConflictError):
    code = "email_in_use"
    message = (
        "An account already uses this email address. Contact us and we will link the listing to it."
    )


class NoClaimEmailError(ConflictError):
    code = "no_claim_email"
    message = "This listing has no email address on file. Add one before sending an invitation."


async def _unclaimed_listing(session: AsyncSession, slug: str) -> Installer:
    installer = await session.scalar(
        select(Installer).where(
            Installer.slug == slug, Installer.status == InstallerStatus.APPROVED
        )
    )
    if installer is None:
        raise NotFoundError("Installer not found.")
    return installer


async def request_claim(session: AsyncSession, slug: str, email: str) -> list[Email]:
    """A business asks to claim its listing from the profile page.

    When the email matches the one on file, it receives a claim link. Otherwise the team is
    told, so it can check the request by hand. The response never says which happened.
    """
    installer = await _unclaimed_listing(session, slug)
    if installer.is_claimed:
        return [emails.claim_already_claimed(installer, email)]
    if installer.contact_email and installer.contact_email.lower() == email.lower():
        token = security.create_listing_claim_token(installer.id, installer.contact_email)
        return [emails.listing_claim_link(installer, installer.contact_email, token)]
    return [emails.claim_needs_review(installer, email)]


async def invite(session: AsyncSession, installer: Installer) -> list[Email]:
    """The admin sends an unclaimed listing its claim link (to the email on file)."""
    if installer.is_claimed:
        raise ListingAlreadyClaimedError
    if not installer.contact_email:
        raise NoClaimEmailError
    token = security.create_listing_claim_token(installer.id, installer.contact_email)
    return [emails.listing_claim_link(installer, installer.contact_email, token, invited=True)]


async def preview(session: AsyncSession, token: str) -> Installer:
    """The listing a claim link is for, so the page can name it before a password is set."""
    claim = _decode(token)
    installer = await session.get(Installer, claim.installer_id)
    if installer is None or installer.contact_email != claim.email:
        raise InvalidTokenError
    if installer.is_claimed:
        raise ListingAlreadyClaimedError
    return installer


async def claim(session: AsyncSession, token: str, password: str) -> User:
    """Create the business's account and link it to the listing."""
    claim_data = _decode(token)
    installer = await session.scalar(
        select(Installer)
        .where(Installer.id == claim_data.installer_id)
        .options(joinedload(Installer.user))
        .with_for_update(of=Installer)
    )
    if installer is None or installer.contact_email != claim_data.email:
        raise InvalidTokenError
    if installer.is_claimed:
        raise ListingAlreadyClaimedError
    if await session.scalar(select(User.id).where(User.email == claim_data.email)) is not None:
        raise EmailInUseError

    now = utcnow()
    user = User(
        email=claim_data.email,
        password_hash=await security.hash_password(password),
        role=Role.INSTALLER,
        email_verified_at=now,
        last_login_at=now,
    )
    installer.user = user
    installer.claimed_at = now
    try:
        await session.commit()
    except IntegrityError as exc:  # a concurrent claim, or the email was just registered
        await session.rollback()
        raise ListingAlreadyClaimedError from exc
    logger.info("Listing %s claimed", installer.slug)
    return user


def _decode(token: str) -> security.ListingClaim:
    try:
        return security.decode_listing_claim_token(token)
    except security.TokenError as exc:
        raise InvalidTokenError from exc
