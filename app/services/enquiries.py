"""Enquiries sent from the "Request a Quote" form on an installer's profile.

Every approved installer's profile has the form. Where the request goes depends on the
plan: Pro and Premium installers receive it themselves (their plan includes enquiries);
requests to Free-plan, listed-only installers go to the PickASparky team, who reply to
the customer. The `accepts_direct_quotes` capability in `app/core/plans.py` decides.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core import security
from app.core.enums import InstallerStatus
from app.core.exceptions import NotFoundError
from app.core.plans import capabilities_for
from app.models import Installer, InstallerEnquiry
from app.schemas.enquiry import EnquiryCreate
from app.services import email as emails
from app.services.email import Email


async def create(
    session: AsyncSession, slug: str, data: EnquiryCreate, client_ip: str
) -> list[Email]:
    """Store the enquiry; return the notification (installer or team) and the customer's copy."""
    installer = await session.scalar(
        select(Installer)
        .where(Installer.slug == slug, Installer.status == InstallerStatus.APPROVED)
        .options(joinedload(Installer.user))
    )
    if installer is None:
        raise NotFoundError("Installer not found.")

    # Unclaimed listings and Free-plan installers: the team handles the request.
    direct = installer.user is not None and capabilities_for(installer.plan).accepts_direct_quotes
    enquiry = InstallerEnquiry(
        installer_id=installer.id,
        name=data.name,
        email=data.email,
        phone=data.phone,
        message=data.message,
        ip_hash=security.hash_ip(client_ip),
        sent_to_installer=direct,
    )
    session.add(enquiry)
    await session.commit()
    notification = (
        emails.installer_enquiry(enquiry, installer, installer.user.email)
        if direct and installer.user is not None
        else emails.enquiry_for_team(
            enquiry, installer, installer.user.email if installer.user else installer.contact_email
        )
    )
    return [notification, emails.enquiry_ack(enquiry, installer)]


async def list_for_installer(
    session: AsyncSession, installer: Installer, *, offset: int, limit: int
) -> tuple[list[InstallerEnquiry], int]:
    """The enquiries the installer was sent, newest first."""
    owned = (InstallerEnquiry.installer_id == installer.id) & InstallerEnquiry.sent_to_installer
    total = await session.scalar(select(func.count()).select_from(InstallerEnquiry).where(owned))
    found = await session.scalars(
        select(InstallerEnquiry)
        .where(owned)
        .order_by(InstallerEnquiry.created_at.desc(), InstallerEnquiry.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(found), total or 0


async def list_all(
    session: AsyncSession, *, offset: int, limit: int
) -> tuple[list[InstallerEnquiry], int]:
    """Every enquiry, newest first, with its installer (back office)."""
    total = await session.scalar(select(func.count()).select_from(InstallerEnquiry))
    found = await session.scalars(
        select(InstallerEnquiry)
        .options(joinedload(InstallerEnquiry.installer))
        .order_by(InstallerEnquiry.created_at.desc(), InstallerEnquiry.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(found), total or 0
