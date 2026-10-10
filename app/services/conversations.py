"""In-app quotes and messages between an installer and a homeowner, kept as history.

A conversation is opened by the installer from a lead or a direct enquiry. Each new
message or quote is stored, then the other side is emailed: the homeowner gets a private
link (no account needed) where they can read the thread, reply, and accept or decline a
quote; the installer is pointed to their dashboard. Emails carry a Reply-To of the other
person, so people who prefer email can simply reply.
"""

import secrets
import uuid
from collections.abc import Callable
from typing import Literal

from sqlalchemy import ColumnElement, func, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core import security
from app.core.enums import LeadStatus, MessageSender, OfferStatus
from app.core.exceptions import ConflictError, ForbiddenError, InvalidTokenError, NotFoundError
from app.core.plans import capabilities_for
from app.models import (
    Conversation,
    ConversationMessage,
    Installer,
    InstallerEnquiry,
    Offer,
    QuoteMatch,
    User,
)
from app.models.base import utcnow
from app.schemas.conversation import (
    ConversationDetail,
    ConversationJob,
    ConversationStart,
    ConversationSummary,
    MessageOut,
    OfferCreate,
    OfferOut,
)
from app.services import email as emails
from app.services.email import Email, quote_summary

OFFER_REFERENCE_PREFIX = "QT-"
_REFERENCE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_REFERENCE_LENGTH = 6
_REFERENCE_ATTEMPTS = 5

_DETAIL = (
    joinedload(Conversation.installer).joinedload(Installer.user),
    joinedload(Conversation.quote_match).joinedload(QuoteMatch.quote_request),
    joinedload(Conversation.enquiry),
    selectinload(Conversation.messages),
    selectinload(Conversation.offers),
)


class LeadsNotIncludedError(ForbiddenError):
    code = "plan_required"
    message = "Upgrade to Pro or Premium to reply to customers and send quotes."


class OfferNotOpenError(ConflictError):
    code = "quote_not_open"
    message = "This quote has already been answered or withdrawn."


# ---- Installer -------------------------------------------------------------------------


def _require_leads(installer: Installer) -> None:
    if installer.user_id is None or not capabilities_for(installer.plan).receives_leads:
        raise LeadsNotIncludedError


async def start(
    session: AsyncSession, installer: Installer, data: ConversationStart
) -> Conversation:
    """Open (or return the existing) conversation for one of the installer's jobs."""
    _require_leads(installer)
    existing = await session.scalar(
        select(Conversation.id).where(
            Conversation.installer_id == installer.id,
            Conversation.quote_match_id == data.lead_id
            if data.lead_id
            else Conversation.enquiry_id == data.enquiry_id,
        )
    )
    if existing is not None:
        return await _load(session, existing)

    if data.lead_id is not None:
        lead = await session.scalar(
            select(QuoteMatch)
            .where(QuoteMatch.id == data.lead_id, QuoteMatch.installer_id == installer.id)
            .options(joinedload(QuoteMatch.quote_request))
        )
        if lead is None:
            raise NotFoundError("Lead not found.")
        conversation = Conversation(
            installer_id=installer.id,
            quote_match_id=lead.id,
            homeowner_name=lead.quote_request.first_name,
            homeowner_email=lead.quote_request.email,
            last_message_at=utcnow(),
        )
        if lead.status is LeadStatus.SENT:
            lead.status = LeadStatus.VIEWED
    else:
        enquiry = await session.scalar(
            select(InstallerEnquiry).where(
                InstallerEnquiry.id == data.enquiry_id,
                InstallerEnquiry.installer_id == installer.id,
                InstallerEnquiry.sent_to_installer,
            )
        )
        if enquiry is None:
            raise NotFoundError("Enquiry not found.")
        conversation = Conversation(
            installer_id=installer.id,
            enquiry_id=enquiry.id,
            homeowner_name=enquiry.name,
            homeowner_email=enquiry.email,
            last_message_at=utcnow(),
        )
    session.add(conversation)
    try:
        await session.commit()
    except IntegrityError:  # opened concurrently: use the other one
        await session.rollback()
        return await start(session, installer, data)
    return await _load(session, conversation.id)


async def list_for_installer(
    session: AsyncSession,
    installer: Installer,
    *,
    unread_only: bool = False,
    offset: int,
    limit: int,
) -> tuple[list[ConversationSummary], int]:
    owned = Conversation.installer_id == installer.id
    return await _summaries(
        session, [owned], reader="installer", unread_only=unread_only, offset=offset, limit=limit
    )


async def get_for_installer(
    session: AsyncSession, installer: Installer, conversation_id: uuid.UUID
) -> ConversationDetail:
    conversation = await _owned(session, installer, conversation_id)
    conversation.installer_read_at = utcnow()
    await session.commit()
    return _detail(conversation, include_email=True)


async def installer_message(
    session: AsyncSession,
    installer: Installer,
    user: User,
    conversation_id: uuid.UUID,
    body: str,
) -> tuple[MessageOut, list[Email]]:
    _require_leads(installer)
    conversation = await _owned(session, installer, conversation_id, lock=True)
    message = _add_message(conversation, MessageSender.INSTALLER, body, author=user)
    conversation.installer_read_at = message.created_at
    _mark_contacted(conversation)
    await session.commit()
    link = _homeowner_link(conversation)
    return MessageOut.model_validate(message), [
        emails.conversation_message_to_homeowner(conversation, installer, body, link)
    ]


async def send_offer(
    session: AsyncSession,
    installer: Installer,
    user: User,
    conversation_id: uuid.UUID,
    data: OfferCreate,
) -> tuple[OfferOut, list[Email]]:
    _require_leads(installer)
    conversation = await _owned(session, installer, conversation_id, lock=True)
    offer = Offer(
        id=uuid.uuid7(),
        conversation_id=conversation.id,
        installer_id=installer.id,
        reference=await _unused_reference(session),
        amount=data.amount,
        includes_vat=data.includes_vat,
        description=data.description,
        valid_until=data.valid_until,
        status=OfferStatus.SENT,
        created_at=utcnow(),
    )
    session.add(offer)
    conversation.offers.append(offer)
    if data.message:
        _add_message(conversation, MessageSender.INSTALLER, data.message, author=user)
    conversation.last_message_at = offer.created_at
    conversation.installer_read_at = offer.created_at
    _mark_contacted(conversation)
    await session.commit()
    link = _homeowner_link(conversation)
    return OfferOut.model_validate(offer), [
        emails.conversation_offer_to_homeowner(conversation, installer, offer, data.message, link)
    ]


async def withdraw_offer(
    session: AsyncSession, installer: Installer, offer_id: uuid.UUID
) -> OfferOut:
    offer = await session.scalar(
        select(Offer)
        .where(Offer.id == offer_id, Offer.installer_id == installer.id)
        .with_for_update()
    )
    if offer is None:
        raise NotFoundError("Quote not found.")
    if offer.status is not OfferStatus.SENT:
        raise OfferNotOpenError
    offer.status = OfferStatus.WITHDRAWN
    offer.responded_at = utcnow()
    session.add(
        ConversationMessage(
            conversation_id=offer.conversation_id,
            sender=MessageSender.SYSTEM,
            body=f"Quote {offer.reference} was withdrawn by the installer.",
        )
    )
    await session.commit()
    return OfferOut.model_validate(offer)


async def installer_offers(
    session: AsyncSession, installer: Installer, *, offset: int, limit: int
) -> tuple[list[tuple[Offer, Conversation]], int]:
    """The installer's quotes, newest first, with their conversation."""
    owned = Offer.installer_id == installer.id
    total = await session.scalar(select(func.count()).select_from(Offer).where(owned))
    rows = await session.execute(
        select(Offer, Conversation)
        .join(Conversation, Conversation.id == Offer.conversation_id)
        .where(owned)
        .order_by(Offer.created_at.desc(), Offer.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return [(offer, conversation) for offer, conversation in rows], total or 0


# ---- Homeowner (private link) ----------------------------------------------------------


async def _from_token(session: AsyncSession, token: str, *, lock: bool = False) -> Conversation:
    try:
        conversation_id = security.decode_conversation_token(token)
    except security.TokenError as exc:
        raise InvalidTokenError from exc
    return await _load(session, conversation_id, lock=lock, via_link=True)


async def get_for_homeowner(session: AsyncSession, token: str) -> ConversationDetail:
    conversation = await _from_token(session, token)
    conversation.homeowner_read_at = utcnow()
    await session.commit()
    return _detail(conversation, include_email=False)


async def homeowner_message(
    session: AsyncSession, token: str, body: str
) -> tuple[MessageOut, list[Email]]:
    conversation = await _from_token(session, token, lock=True)
    message = _add_message(conversation, MessageSender.HOMEOWNER, body)
    conversation.homeowner_read_at = message.created_at
    await session.commit()
    return MessageOut.model_validate(message), _notify_installer(
        conversation, lambda to: emails.conversation_reply_to_installer(conversation, body, to)
    )


async def respond_to_offer(
    session: AsyncSession,
    token: str,
    offer_id: uuid.UUID,
    decision: Literal["accept", "decline"],
    note: str | None,
) -> tuple[OfferOut, list[Email]]:
    conversation = await _from_token(session, token, lock=True)
    offer = next((item for item in conversation.offers if item.id == offer_id), None)
    if offer is None:
        raise NotFoundError("Quote not found.")
    if offer.status is not OfferStatus.SENT:
        raise OfferNotOpenError
    now = utcnow()
    offer.status = OfferStatus.ACCEPTED if decision == "accept" else OfferStatus.DECLINED
    offer.responded_at = now
    offer.response_note = note
    verb = "accepted" if decision == "accept" else "declined"
    _add_message(
        conversation,
        MessageSender.SYSTEM,
        f"{conversation.homeowner_name} {verb} quote {offer.reference}."
        + (f"\n\n{note}" if note else ""),
    )
    conversation.homeowner_read_at = now
    await session.commit()
    return OfferOut.model_validate(offer), _notify_installer(
        conversation, lambda to: emails.offer_response_to_installer(conversation, offer, to)
    )


# ---- Back office -----------------------------------------------------------------------


async def list_all(
    session: AsyncSession, *, installer_id: uuid.UUID | None, offset: int, limit: int
) -> tuple[list[ConversationSummary], int]:
    filters = [Conversation.installer_id == installer_id] if installer_id else []
    return await _summaries(session, filters, reader="admin", offset=offset, limit=limit)


async def get_any(session: AsyncSession, conversation_id: uuid.UUID) -> ConversationDetail:
    return _detail(await _load(session, conversation_id), include_email=True)


# ---- Helpers ---------------------------------------------------------------------------


async def _load(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    *,
    lock: bool = False,
    via_link: bool = False,
) -> Conversation:
    statement = (
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(*_DETAIL)
        .execution_options(populate_existing=True)
    )
    if lock:
        statement = statement.with_for_update(of=Conversation)
    conversation = await session.scalar(statement)
    if conversation is None:
        # A link to a conversation that no longer exists reads as an expired link.
        raise InvalidTokenError if via_link else NotFoundError("Conversation not found.")
    return conversation


async def _owned(
    session: AsyncSession, installer: Installer, conversation_id: uuid.UUID, *, lock: bool = False
) -> Conversation:
    conversation = await _load(session, conversation_id, lock=lock)
    if conversation.installer_id != installer.id:
        raise NotFoundError("Conversation not found.")
    return conversation


def _add_message(
    conversation: Conversation, sender: MessageSender, body: str, *, author: User | None = None
) -> ConversationMessage:
    now = utcnow()
    message = ConversationMessage(
        id=uuid.uuid7(),
        conversation_id=conversation.id,
        sender=sender,
        author_user_id=author.id if author else None,
        body=body,
        created_at=now,
        updated_at=now,
    )
    conversation.messages.append(message)
    conversation.last_message_at = now
    return message


def _mark_contacted(conversation: Conversation) -> None:
    """Replying to a lead moves it on from "sent" or "viewed" to "contacted"."""
    lead = conversation.quote_match
    if lead is not None and lead.status in (LeadStatus.SENT, LeadStatus.VIEWED):
        lead.status = LeadStatus.CONTACTED


def _homeowner_link(conversation: Conversation) -> str:
    return emails.conversation_link(security.create_conversation_token(conversation.id))


def _notify_installer(conversation: Conversation, build: Callable[[str], Email]) -> list[Email]:
    user = conversation.installer.user
    return [build(user.email)] if user is not None else []


def _job(conversation: Conversation) -> ConversationJob:
    if conversation.quote_match is not None:
        quote = conversation.quote_match.quote_request
        return ConversationJob(
            kind="lead",
            reference=quote.reference,
            summary=quote_summary(quote),
            message=quote.notes,
            phone=quote.phone,
            created_at=quote.created_at,
        )
    enquiry = conversation.enquiry
    if enquiry is None:  # ruled out by the exactly_one_job check constraint
        raise NotFoundError("Conversation not found.")
    return ConversationJob(
        kind="enquiry",
        reference=None,
        summary=[],
        message=enquiry.message,
        phone=enquiry.phone,
        created_at=enquiry.created_at,
    )


def _detail(conversation: Conversation, *, include_email: bool) -> ConversationDetail:
    job = _job(conversation)
    if not include_email:
        job = job.model_copy(update={"phone": None})
    return ConversationDetail(
        id=conversation.id,
        installer_name=conversation.installer.business_name,
        installer_slug=conversation.installer.slug,
        homeowner_name=conversation.homeowner_name,
        homeowner_email=conversation.homeowner_email if include_email else None,
        job=job,
        messages=[MessageOut.model_validate(message) for message in conversation.messages],
        offers=[OfferOut.model_validate(offer) for offer in conversation.offers],
        created_at=conversation.created_at,
    )


async def _summaries(
    session: AsyncSession,
    filters: list[ColumnElement[bool]],
    *,
    reader: Literal["installer", "homeowner", "admin"],
    unread_only: bool = False,
    offset: int,
    limit: int,
) -> tuple[list[ConversationSummary], int]:
    if unread_only:
        filters = [*filters, _unread_for_installer()]
    total = await session.scalar(select(func.count()).select_from(Conversation).where(*filters))
    conversations = list(
        await session.scalars(
            select(Conversation)
            .where(*filters)
            .options(joinedload(Conversation.installer), selectinload(Conversation.offers))
            .order_by(Conversation.last_message_at.desc(), Conversation.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    latest = await _latest_messages(session, [conversation.id for conversation in conversations])
    return [
        ConversationSummary.build(conversation, latest.get(conversation.id), reader=reader)
        for conversation in conversations
    ], total or 0


def _unread_for_installer() -> ColumnElement[bool]:
    """A homeowner or the team wrote after the installer last opened the conversation."""
    newer = select(ConversationMessage.id).where(
        ConversationMessage.conversation_id == Conversation.id,
        ConversationMessage.sender.in_((MessageSender.HOMEOWNER, MessageSender.TEAM)),
        (Conversation.installer_read_at.is_(None))
        | (ConversationMessage.created_at > Conversation.installer_read_at),
    )
    return newer.exists()


async def count_unread_for_installer(session: AsyncSession, installer: Installer) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.installer_id == installer.id, _unread_for_installer())
        )
        or 0
    )


async def _latest_messages(
    session: AsyncSession, conversation_ids: list[uuid.UUID]
) -> dict[uuid.UUID, ConversationMessage]:
    """The newest message of each conversation, in one query."""
    if not conversation_ids:
        return {}
    newest = (
        select(
            ConversationMessage.conversation_id,
            func.max(ConversationMessage.created_at).label("created_at"),
        )
        .where(ConversationMessage.conversation_id.in_(conversation_ids))
        .group_by(ConversationMessage.conversation_id)
        .subquery()
    )
    messages = await session.scalars(
        select(ConversationMessage).where(
            tuple_(ConversationMessage.conversation_id, ConversationMessage.created_at).in_(
                select(newest.c.conversation_id, newest.c.created_at)
            )
        )
    )
    return {message.conversation_id: message for message in messages}


def _random_reference() -> str:
    code = "".join(secrets.choice(_REFERENCE_ALPHABET) for _ in range(_REFERENCE_LENGTH))
    return f"{OFFER_REFERENCE_PREFIX}{code}"


async def _unused_reference(session: AsyncSession) -> str:
    for _ in range(_REFERENCE_ATTEMPTS):
        reference = _random_reference()
        if await session.scalar(select(Offer.id).where(Offer.reference == reference)) is None:
            return reference
    raise RuntimeError("Could not generate an unused quote reference")
