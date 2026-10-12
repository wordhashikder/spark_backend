"""An installer's leads: listing them and tracking their progress."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core import security
from app.core.enums import LeadStatus
from app.core.exceptions import NotFoundError
from app.models import Conversation, Installer, Offer, QuoteMatch, QuoteRequest
from app.models.base import utcnow
from app.schemas.quote import LeadProgress
from app.services import email as emails
from app.services import lead_stats
from app.services.email import Email
from app.services.geo import distance_miles


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


async def progress(
    session: AsyncSession, installer: Installer, leads: list[QuoteMatch]
) -> dict[uuid.UUID, LeadProgress]:
    """Progress for a page of the installer's leads, in one query."""
    if not leads:
        return {}
    conversation_id = (
        select(Conversation.id)
        .where(Conversation.quote_match_id == QuoteMatch.id)
        .correlate(QuoteMatch)
        .scalar_subquery()
    )
    my_quote = (
        select(Offer.status)
        .join(Conversation, Conversation.id == Offer.conversation_id)
        .where(Conversation.quote_match_id == QuoteMatch.id)
        .order_by(Offer.created_at.desc())
        .limit(1)
        .correlate(QuoteMatch)
        .scalar_subquery()
    )
    miles = distance_miles(
        QuoteRequest.latitude, QuoteRequest.longitude, installer.latitude, installer.longitude
    )
    rows = await session.execute(
        select(
            QuoteMatch.id,
            lead_stats.installers_matched(),
            lead_stats.quotes_sent(),
            miles,
            conversation_id,
            my_quote,
        )
        .join(QuoteRequest, QuoteRequest.id == QuoteMatch.quote_request_id)
        .where(QuoteMatch.id.in_([lead.id for lead in leads]))
    )
    return {
        lead_id: LeadProgress(
            installers_matched=matched or 0,
            quotes_sent=sent or 0,
            distance_miles=None if distance is None else round(float(distance), 1),
            conversation_id=conversation,
            my_quote_status=status,
        )
        for lead_id, matched, sent, distance, conversation, status in rows
    }
