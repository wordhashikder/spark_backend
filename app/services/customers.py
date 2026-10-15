"""Customers: records created from quote requests, magic-link sign-in and their dashboard.

A customer never sets a password. Each quote request emails a magic link; opening it starts
a session (an opaque token kept in an httpOnly cookie by the website), so later visits
need no new link. Tokens are random, stored only as hashes, expire, and every failure
looks the same to the caller.
"""

import logging
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core import security
from app.core.config import get_settings
from app.core.enums import InstallerStatus, MessageSender, OfferStatus
from app.core.exceptions import InvalidTokenError, NotAuthenticatedError, NotFoundError
from app.models import (
    Conversation,
    ConversationMessage,
    Customer,
    CustomerLoginLink,
    CustomerSession,
    Installer,
    Offer,
    QuoteMatch,
    QuoteRequest,
)
from app.models.base import utcnow
from app.schemas.admin import AdminCustomer
from app.schemas.customer import (
    CustomerOut,
    CustomerQuoteOut,
    CustomerSessionOut,
    InstallerBrief,
    JourneyStep,
    MatchedInstallerOut,
    RequestDetailOut,
    RequestSummaryOut,
)
from app.services import email as emails
from app.services.email import Email, quote_summary

logger = logging.getLogger(__name__)

# An email scanner often opens a link before the person does; the same link keeps working
# for a few minutes after its first use so the real click still signs them in.
USED_LINK_GRACE = timedelta(minutes=10)
_TOUCH_INTERVAL = timedelta(minutes=5)
_MAX_ACTIVE_LINKS = 10

_JOURNEY = (
    ("submitted", "Request sent"),
    ("matched", "Installers matched"),
    ("quotes", "Quotes received"),
    ("choose", "Choose your installer"),
    ("install", "Installation"),
)


def _out(customer: Customer) -> CustomerOut:
    return CustomerOut(
        id=customer.id,
        email=customer.email,
        first_name=customer.first_name,
        phone=customer.phone,
        created_at=customer.created_at,
    )


# ---- Records ---------------------------------------------------------------------------


async def get_or_create(
    session: AsyncSession, email: str, first_name: str, phone: str | None
) -> Customer:
    """The customer for `email`, created on first use. The latest name/phone are kept."""
    email = email.lower()
    customer = await session.scalar(select(Customer).where(Customer.email == email))
    if customer is None:
        customer = Customer(email=email, first_name=first_name, phone=phone)
        session.add(customer)
        await session.flush()
        return customer
    customer.first_name = first_name
    if phone:
        customer.phone = phone
    return customer


# ---- Magic links -----------------------------------------------------------------------


def link_url(token: str) -> str:
    return f"{get_settings().frontend_url}/uk/my-quotes/verify/?token={token}"


async def issue_link(session: AsyncSession, customer: Customer) -> str:
    """A new magic link token for `customer` (no commit). Old expired links are cleared."""
    now = utcnow()
    await session.execute(
        delete(CustomerLoginLink).where(
            CustomerLoginLink.customer_id == customer.id, CustomerLoginLink.expires_at < now
        )
    )
    active = list(
        await session.scalars(
            select(CustomerLoginLink.id)
            .where(CustomerLoginLink.customer_id == customer.id)
            .order_by(CustomerLoginLink.created_at.desc())
            .offset(_MAX_ACTIVE_LINKS - 1)
        )
    )
    if active:
        await session.execute(delete(CustomerLoginLink).where(CustomerLoginLink.id.in_(active)))
    token = security.generate_opaque_token()
    session.add(
        CustomerLoginLink(
            customer_id=customer.id,
            token_hash=security.hash_token(token),
            expires_at=now + timedelta(minutes=get_settings().magic_link_expire_minutes),
        )
    )
    return token


async def request_link(session: AsyncSession, email: str) -> list[Email]:
    """ "Email me a new link". Always succeeds from the caller's side (no account probing)."""
    customer = await session.scalar(select(Customer).where(Customer.email == email.lower()))
    if customer is None:
        return []
    token = await issue_link(session, customer)
    await session.commit()
    return [emails.magic_link(customer, link_url(token))]


async def verify_link(session: AsyncSession, token: str) -> CustomerSessionOut:
    """Exchange a magic link token for a session."""
    now = utcnow()
    link = await session.scalar(
        select(CustomerLoginLink)
        .where(CustomerLoginLink.token_hash == security.hash_token(token))
        .with_for_update()
    )
    if (
        link is None
        or link.expires_at <= now
        or (link.used_at is not None and now - link.used_at > USED_LINK_GRACE)
    ):
        raise InvalidTokenError
    customer = await session.get(Customer, link.customer_id)
    if customer is None:  # pragma: no cover - the foreign key cascades
        raise InvalidTokenError
    if link.used_at is None:
        link.used_at = now
    customer.last_login_at = now
    return await _start_session(session, customer)


async def _start_session(session: AsyncSession, customer: Customer) -> CustomerSessionOut:
    settings = get_settings()
    now = utcnow()
    token = security.generate_opaque_token()
    idle = timedelta(days=settings.customer_session_idle_days)
    session.add(
        CustomerSession(
            customer_id=customer.id,
            token_hash=security.hash_token(token),
            expires_at=now + idle,
            absolute_expires_at=now + timedelta(days=settings.customer_session_max_days),
            last_seen_at=now,
        )
    )
    await session.commit()
    return CustomerSessionOut(
        session_token=token, expires_in=int(idle.total_seconds()), customer=_out(customer)
    )


# ---- Sessions --------------------------------------------------------------------------


async def authenticate(session: AsyncSession, token: str) -> Customer:
    """The customer a session token belongs to. Slides the idle expiry on use."""
    now = utcnow()
    record = await session.scalar(
        select(CustomerSession).where(CustomerSession.token_hash == security.hash_token(token))
    )
    if (
        record is None
        or record.revoked_at is not None
        or record.expires_at <= now
        or record.absolute_expires_at <= now
    ):
        raise NotAuthenticatedError(
            "Your session has ended. Please request a new link.", code="invalid_token"
        )
    customer = await session.get(Customer, record.customer_id)
    if customer is None:  # pragma: no cover - the foreign key cascades
        raise NotAuthenticatedError("Your session has ended.", code="invalid_token")
    if now - record.last_seen_at > _TOUCH_INTERVAL:
        idle = timedelta(days=get_settings().customer_session_idle_days)
        record.last_seen_at = now
        record.expires_at = min(now + idle, record.absolute_expires_at)
        await session.commit()
    return customer


async def sign_out(session: AsyncSession, token: str) -> None:
    record = await session.scalar(
        select(CustomerSession).where(CustomerSession.token_hash == security.hash_token(token))
    )
    if record is not None and record.revoked_at is None:
        record.revoked_at = utcnow()
        await session.commit()


async def update_profile(
    session: AsyncSession, customer: Customer, first_name: str | None, phone: str | None
) -> CustomerOut:
    if first_name:
        customer.first_name = first_name
    customer.phone = phone
    await session.commit()
    return _out(customer)


async def erase(session: AsyncSession, customer: Customer) -> None:
    """Delete the customer's sign-in data and detach their requests (GDPR erase / admin)."""
    await session.execute(delete(Customer).where(Customer.id == customer.id))
    await session.commit()


def profile(customer: Customer) -> CustomerOut:
    return _out(customer)


# ---- Dashboard -------------------------------------------------------------------------


def installer_brief(installer: Installer) -> InstallerBrief:
    return InstallerBrief(
        slug=installer.slug,
        business_name=installer.business_name,
        town=installer.town,
        logo_url=installer.logo_url,
        rating_avg=None if installer.rating_avg is None else float(installer.rating_avg),
        review_count=installer.review_count,
        verified=installer.status is InstallerStatus.APPROVED and installer.is_claimed,
        years_experience=installer.years_experience,
        accreditations=[item.scheme.label for item in installer.accreditations if item.verified],
        plan=installer.plan.value,
    )


def _status(
    quote: QuoteRequest, matched: int, open_quotes: int, accepted: bool
) -> tuple[str, str, str]:
    """`(key, label, one line of detail)` for the request."""
    if accepted:
        return "accepted", "Quote accepted", "Your installer will be in touch to arrange the work."
    if open_quotes:
        return (
            "quotes_received",
            "Quotes received",
            "Compare your quotes and message the installers before you choose.",
        )
    if matched:
        return (
            "matching",
            "Active - Matching with installers",
            "Installers have your request and are preparing their quotes.",
        )
    if quote.status.value == "new":
        return (
            "reviewing",
            "Being reviewed",
            "Our team is choosing the best local installers for your job.",
        )
    return (
        "waiting",
        "Waiting for installers",
        "We don't have an installer in your area yet. We'll email you when one is available.",
    )


def _journey(status: str, matched: int, open_quotes: int, accepted: bool) -> list[JourneyStep]:
    reached = 1
    if matched:
        reached = 2
    if open_quotes or accepted:
        reached = 3
    if accepted:
        reached = 4
    steps: list[JourneyStep] = []
    for index, (key, label) in enumerate(_JOURNEY, start=1):
        state = "done" if index <= reached else "upcoming"
        if index == reached + 1:
            state = "current"
        steps.append(JourneyStep(key=key, label=label, state=state))
    return steps


async def _unread_by_conversation(session: AsyncSession, conversation_ids: list[uuid.UUID]) -> int:
    if not conversation_ids:
        return 0
    newer = select(ConversationMessage.id).where(
        ConversationMessage.conversation_id == Conversation.id,
        ConversationMessage.sender.in_((MessageSender.INSTALLER, MessageSender.TEAM)),
        (Conversation.homeowner_read_at.is_(None))
        | (ConversationMessage.created_at > Conversation.homeowner_read_at),
    )
    new_quote = select(Offer.id).where(
        Offer.conversation_id == Conversation.id,
        (Conversation.homeowner_read_at.is_(None))
        | (Offer.created_at > Conversation.homeowner_read_at),
    )
    return (
        await session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.id.in_(conversation_ids), or_(newer.exists(), new_quote.exists()))
        )
        or 0
    )


async def count_unread(session: AsyncSession, customer: Customer) -> int:
    ids = list(
        await session.scalars(
            select(Conversation.id).where(
                func.lower(Conversation.homeowner_email) == customer.email
            )
        )
    )
    return await _unread_by_conversation(session, ids)


async def _load_requests(session: AsyncSession, customer: Customer) -> list[QuoteRequest]:
    return list(
        await session.scalars(
            select(QuoteRequest)
            .where(QuoteRequest.customer_id == customer.id)
            .order_by(QuoteRequest.created_at.desc())
        )
    )


async def _request_parts(
    session: AsyncSession, quote: QuoteRequest
) -> tuple[list[QuoteMatch], dict[uuid.UUID, Conversation]]:
    matches = list(
        await session.scalars(
            select(QuoteMatch)
            .where(QuoteMatch.quote_request_id == quote.id)
            .options(
                joinedload(QuoteMatch.installer).selectinload(Installer.accreditations),
            )
            .order_by(QuoteMatch.created_at)
        )
    )
    conversations = {
        conversation.quote_match_id: conversation
        for conversation in await session.scalars(
            select(Conversation)
            .where(Conversation.quote_match_id.in_([match.id for match in matches]))
            .options(selectinload(Conversation.offers))
        )
        if conversation.quote_match_id is not None
    }
    return matches, conversations


def _money(values: list[Decimal]) -> tuple[Decimal | None, Decimal | None]:
    if not values:
        return None, None
    return (sum(values) / len(values)).quantize(Decimal("0.01")), min(values)


async def _summary_and_parts(
    session: AsyncSession, quote: QuoteRequest, slots_total: int
) -> tuple[RequestSummaryOut, list[QuoteMatch], dict[uuid.UUID, Conversation]]:
    matches, conversations = await _request_parts(session, quote)
    offers = [offer for conversation in conversations.values() for offer in conversation.offers]
    open_offers = [o for o in offers if o.status in (OfferStatus.SENT, OfferStatus.ACCEPTED)]
    accepted = any(o.status is OfferStatus.ACCEPTED for o in offers)
    key, label, detail = _status(quote, len(matches), len(open_offers), accepted)
    average, lowest = _money([o.amount for o in open_offers])
    summary = RequestSummaryOut(
        id=quote.id,
        reference=quote.reference,
        postcode=quote.postcode,
        district=quote.district,
        installation_type=quote.installation_type.label,
        timing=quote.timing.label,
        status=key,
        status_label=label,
        status_detail=detail,
        created_at=quote.created_at,
        installers_matched=len(matches),
        quotes_received=len(open_offers),
        slots_total=max(slots_total, len(matches)),
        average_price=average,
        lowest_price=lowest,
        unread_messages=await _unread_by_conversation(
            session, [conversation.id for conversation in conversations.values()]
        ),
    )
    return summary, matches, conversations


async def overview(
    session: AsyncSession, customer: Customer, slots_total: int
) -> tuple[list[RequestSummaryOut], int]:
    summaries = [
        (await _summary_and_parts(session, quote, slots_total))[0]
        for quote in await _load_requests(session, customer)
    ]
    return summaries, await count_unread(session, customer)


async def request_detail(
    session: AsyncSession, customer: Customer, request_id: uuid.UUID, slots_total: int
) -> RequestDetailOut:
    quote = await session.scalar(
        select(QuoteRequest).where(
            QuoteRequest.id == request_id, QuoteRequest.customer_id == customer.id
        )
    )
    if quote is None:
        raise NotFoundError("Request not found.")
    summary, matches, conversations = await _summary_and_parts(session, quote, slots_total)
    quotes: list[CustomerQuoteOut] = []
    installers: list[MatchedInstallerOut] = []
    for match in matches:
        brief = installer_brief(match.installer)
        conversation = conversations.get(match.id)
        offers = conversation.offers if conversation else []
        latest = offers[-1] if offers else None
        for offer in offers:
            if offer.status is OfferStatus.WITHDRAWN:
                continue
            quotes.append(_quote_out(offer, brief, conversation.id if conversation else None))
        if latest is None or latest.status is OfferStatus.WITHDRAWN:
            state = "awaiting_quote"
        elif latest.status is OfferStatus.ACCEPTED:
            state = "accepted"
        elif latest.status is OfferStatus.DECLINED:
            state = "declined"
        else:
            state = "quoted"
        installers.append(
            MatchedInstallerOut(
                installer=brief,
                state=state,
                conversation_id=conversation.id if conversation else None,
            )
        )
    open_quotes = [q for q in quotes if q.status in (OfferStatus.SENT, OfferStatus.ACCEPTED)]
    if len(open_quotes) > 1:
        cheapest = min(open_quotes, key=lambda q: q.amount)
        cheapest.highlight = "lowest"
    quotes.sort(key=lambda q: (q.status is OfferStatus.DECLINED, q.amount))
    accepted = any(q.status is OfferStatus.ACCEPTED for q in quotes)
    return RequestDetailOut(
        **summary.model_dump(),
        answers=quote_summary(quote),
        journey=_journey(summary.status, summary.installers_matched, len(open_quotes), accepted),
        quotes=quotes,
        installers=installers,
        conversation_ids=[conversation.id for conversation in conversations.values()],
    )


def _quote_out(
    offer: Offer, installer: InstallerBrief, conversation_id: uuid.UUID | None
) -> CustomerQuoteOut:
    return CustomerQuoteOut(
        id=offer.id,
        reference=offer.reference,
        amount=offer.amount,
        includes_vat=offer.includes_vat,
        description=offer.description,
        valid_until=offer.valid_until,
        status=offer.status,
        created_at=offer.created_at,
        conversation_id=conversation_id or offer.conversation_id,
        installer=installer,
    )


# ---- Back office -----------------------------------------------------------------------


async def admin_list(
    session: AsyncSession, *, search: str | None, offset: int, limit: int
) -> tuple[list[AdminCustomer], int]:
    filters = []
    if search and search.strip():
        escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        filters.append(
            or_(
                Customer.email.ilike(pattern, escape="\\"),
                Customer.first_name.ilike(pattern, escape="\\"),
            )
        )
    total = await session.scalar(select(func.count()).select_from(Customer).where(*filters))
    requests = (
        select(func.count())
        .where(QuoteRequest.customer_id == Customer.id)
        .correlate(Customer)
        .scalar_subquery()
    )
    threads = (
        select(func.count())
        .where(func.lower(Conversation.homeowner_email) == Customer.email)
        .correlate(Customer)
        .scalar_subquery()
    )
    quotes = (
        select(func.count())
        .select_from(Offer)
        .join(Conversation, Conversation.id == Offer.conversation_id)
        .where(func.lower(Conversation.homeowner_email) == Customer.email)
        .correlate(Customer)
        .scalar_subquery()
    )
    rows = await session.execute(
        select(Customer, requests, threads, quotes)
        .where(*filters)
        .order_by(Customer.created_at.desc(), Customer.id)
        .offset(offset)
        .limit(limit)
    )
    return [
        AdminCustomer(
            id=customer.id,
            email=customer.email,
            first_name=customer.first_name,
            phone=customer.phone,
            created_at=customer.created_at,
            last_login_at=customer.last_login_at,
            requests=request_count or 0,
            conversations=thread_count or 0,
            quotes_received=quote_count or 0,
        )
        for customer, request_count, thread_count, quote_count in rows
    ], total or 0


async def admin_get(session: AsyncSession, customer_id: uuid.UUID) -> Customer:
    customer = await session.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError("Customer not found.")
    return customer


async def admin_send_link(session: AsyncSession, customer_id: uuid.UUID) -> list[Email]:
    customer = await admin_get(session, customer_id)
    token = await issue_link(session, customer)
    await session.commit()
    return [emails.magic_link(customer, link_url(token))]
