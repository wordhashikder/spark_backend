"""An installer's leads: listing them and tracking their progress."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core import security
from app.core.enums import LeadStatus
from app.core.exceptions import NotFoundError
from app.models import Installer, QuoteMatch
from app.models.base import utcnow
from app.services import email as emails
from app.services.email import Email


async def list_for_installer(
    session: AsyncSession, installer: Installer, *, offset: int, limit: int
) -> tuple[list[QuoteMatch], int]:
    """The installer's leads, newest first, with their quote requests loaded."""
    owned = QuoteMatch.installer_id == installer.id
    total = await session.scalar(select(func.count()).select_from(QuoteMatch).where(owned))
    leads = await session.scalars(
        select(QuoteMatch)
        .where(owned)
        .options(joinedload(QuoteMatch.quote_request))
        .order_by(QuoteMatch.created_at.desc(), QuoteMatch.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(leads), total or 0


async def update_status(
    session: AsyncSession, installer: Installer, lead_id: uuid.UUID, status: LeadStatus
) -> tuple[QuoteMatch, list[Email]]:
    """Move a lead to `status`. The first move to `won` invites the customer to review."""
    lead = await session.scalar(
        select(QuoteMatch)
        .where(QuoteMatch.id == lead_id, QuoteMatch.installer_id == installer.id)
        .options(joinedload(QuoteMatch.quote_request))
        .with_for_update(of=QuoteMatch)
    )
    if lead is None:
        raise NotFoundError("Lead not found.")

    lead.status = status
    outbox: list[Email] = []
    if status is LeadStatus.WON and lead.review_invited_at is None:
        lead.review_invited_at = utcnow()
        token = security.create_review_invite_token(lead.id)
        outbox.append(emails.review_invitation(lead.quote_request, installer, token))
    await session.commit()
    return lead, outbox
