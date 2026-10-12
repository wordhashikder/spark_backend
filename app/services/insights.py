"""The back office's Overview, sidebar badges and global search."""

from datetime import date, timedelta

from sqlalchemy import Date, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    InstallerStatus,
    OfferStatus,
    QuoteStatus,
    ReviewStatus,
)
from app.models import (
    ContactMessage,
    Conversation,
    Installer,
    InstallerEnquiry,
    Location,
    Offer,
    QuoteRequest,
    Review,
)
from app.models.base import utcnow
from app.schemas.admin import (
    AdminOverview,
    CountByKey,
    Kpi,
    MonthlyPoint,
    NavCounts,
    RecentLead,
    SearchHit,
    SearchResults,
)
from app.services import lead_stats

_RECENT_LEADS = 5
_AREAS = 6
_MONTHS = 6
_HITS_PER_KIND = 5


def _change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


async def _count(session: AsyncSession, model: type, *filters) -> int:
    return await session.scalar(select(func.count()).select_from(model).where(*filters)) or 0


def _month_start(day: date, back: int = 0) -> date:
    year, month = day.year, day.month - back
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


async def overview(session: AsyncSession, *, days: int, max_installers: int) -> AdminOverview:
    now = utcnow()
    since = now - timedelta(days=days)
    before = since - timedelta(days=days)

    leads_now = await _count(session, QuoteRequest, QuoteRequest.created_at >= since)
    leads_before = await _count(
        session, QuoteRequest, QuoteRequest.created_at >= before, QuoteRequest.created_at < since
    )
    matched_now = await _count(
        session,
        QuoteRequest,
        QuoteRequest.created_at >= since,
        QuoteRequest.status == QuoteStatus.MATCHED,
    )
    matched_before = await _count(
        session,
        QuoteRequest,
        QuoteRequest.created_at >= before,
        QuoteRequest.created_at < since,
        QuoteRequest.status == QuoteStatus.MATCHED,
    )
    quotes_now = await _count(
        session, Offer, Offer.created_at >= since, Offer.status != OfferStatus.WITHDRAWN
    )
    quotes_before = await _count(
        session,
        Offer,
        Offer.created_at >= before,
        Offer.created_at < since,
        Offer.status != OfferStatus.WITHDRAWN,
    )
    accepted_now = await _count(
        session, Offer, Offer.created_at >= since, Offer.status == OfferStatus.ACCEPTED
    )
    active = (Installer.status == InstallerStatus.APPROVED, Installer.user_id.is_not(None))
    active_installers = await _count(session, Installer, *active)
    new_this_week = await _count(
        session, Installer, *active, Installer.claimed_at >= now - timedelta(days=7)
    ) + await _count(
        session,
        Installer,
        *active,
        Installer.claimed_at.is_(None),
        Installer.approved_at >= now - timedelta(days=7),
    )
    listed = await _count(session, Installer, Installer.status == InstallerStatus.APPROVED)
    match_rate_now = matched_now / leads_now * 100 if leads_now else 0.0
    match_rate_before = matched_before / leads_before * 100 if leads_before else 0.0
    avg_matched = (
        await session.scalar(
            select(func.avg(lead_stats.installers_matched())).where(
                QuoteRequest.created_at >= since, QuoteRequest.status == QuoteStatus.MATCHED
            )
        )
        or 0
    )

    # Monthly leads and quotes for the chart, oldest first, zero-filled.
    first_month = _month_start(now.date(), _MONTHS - 1)
    lead_month = func.date_trunc("month", QuoteRequest.created_at)
    quote_month = func.date_trunc("month", Offer.created_at)
    lead_rows = await session.execute(
        select(cast(lead_month, Date), func.count())
        .where(QuoteRequest.created_at >= first_month)
        .group_by(lead_month)
    )
    quote_rows = await session.execute(
        select(cast(quote_month, Date), func.count())
        .where(Offer.created_at >= first_month, Offer.status != OfferStatus.WITHDRAWN)
        .group_by(quote_month)
    )
    leads_by_month = dict(lead_rows.all())
    quotes_by_month = dict(quote_rows.all())
    monthly = [
        MonthlyPoint(
            month=month,
            leads=leads_by_month.get(month, 0),
            quotes=quotes_by_month.get(month, 0),
        )
        for month in (_month_start(now.date(), back) for back in range(_MONTHS - 1, -1, -1))
    ]

    area = func.coalesce(QuoteRequest.district, QuoteRequest.region, "Unknown area")
    area_rows = await session.execute(
        select(area, func.count())
        .where(QuoteRequest.created_at >= _month_start(now.date()))
        .group_by(area)
        .order_by(func.count().desc(), area)
        .limit(_AREAS)
    )

    recent_rows = await session.execute(
        select(
            QuoteRequest,
            lead_stats.installers_matched(),
            lead_stats.quotes_sent(),
            lead_stats.stage(),
        )
        .order_by(QuoteRequest.created_at.desc(), QuoteRequest.id.desc())
        .limit(_RECENT_LEADS)
    )

    return AdminOverview(
        period_days=days,
        leads=Kpi(
            value=leads_now,
            change=_change(leads_now, leads_before),
            hint=f"vs previous {days} days",
        ),
        active_installers=Kpi(
            value=active_installers,
            change=None,
            hint=f"{new_this_week} new this week · {listed} listed",
        ),
        quotes_sent=Kpi(
            value=quotes_now,
            change=_change(quotes_now, quotes_before),
            hint=f"{accepted_now} accepted",
        ),
        match_rate=Kpi(
            value=round(match_rate_now, 1),
            change=(
                round(match_rate_now - match_rate_before, 1) if leads_before and leads_now else None
            ),
            hint=f"avg {float(avg_matched):.1f} of {max_installers} installers per lead",
        ),
        monthly=monthly,
        leads_by_area=[CountByKey(key=str(key), count=count) for key, count in area_rows],
        recent_leads=[
            RecentLead(
                id=quote.id,
                reference=quote.reference,
                first_name=quote.first_name,
                installation_type=quote.installation_type,
                postcode=quote.postcode,
                district=quote.district,
                created_at=quote.created_at,
                installers_matched=matched or 0,
                quotes_sent=sent or 0,
                max_installers=max_installers,
                stage=current_stage,
            )
            for quote, matched, sent, current_stage in recent_rows
        ],
        held_leads=await _count(session, QuoteRequest, QuoteRequest.status == QuoteStatus.NEW),
        unmatched_leads=await _count(
            session,
            QuoteRequest,
            QuoteRequest.status == QuoteStatus.UNMATCHED,
            QuoteRequest.created_at >= since,
        ),
        installers_pending=await _count(
            session, Installer, Installer.status == InstallerStatus.PENDING
        ),
        reviews_pending=await _count(session, Review, Review.status == ReviewStatus.PENDING),
        enquiries_for_team=await _count(
            session,
            InstallerEnquiry,
            InstallerEnquiry.sent_to_installer.is_(False),
            InstallerEnquiry.created_at >= since,
        ),
        contact_messages_recent=await _count(
            session, ContactMessage, ContactMessage.created_at >= since
        ),
    )


async def nav_counts(session: AsyncSession, access: frozenset[str]) -> NavCounts:
    week = utcnow() - timedelta(days=7)
    counts = NavCounts()
    if "leads" in access:
        # Requests waiting for the team: held for manual matching, or matched nobody.
        counts.leads = await _count(
            session,
            QuoteRequest,
            or_(
                QuoteRequest.status == QuoteStatus.NEW,
                QuoteRequest.status == QuoteStatus.UNMATCHED,
            ),
            QuoteRequest.created_at >= utcnow() - timedelta(days=30),
        )
    if "installers" in access:
        counts.installers = await _count(
            session, Installer, Installer.status == InstallerStatus.PENDING
        )
    if "reviews" in access:
        counts.reviews = await _count(session, Review, Review.status == ReviewStatus.PENDING)
    if "inbox" in access:
        counts.inbox = await _count(session, ContactMessage, ContactMessage.created_at >= week)
    return counts


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def search(session: AsyncSession, query: str, access: frozenset[str]) -> SearchResults:
    term = query.strip()
    hits: list[SearchHit] = []
    if len(term) < 2:
        return SearchResults(query=term, hits=hits)
    pattern = _like(term)

    if "installers" in access:
        found = await session.scalars(
            select(Installer)
            .where(
                or_(
                    Installer.business_name.ilike(pattern, escape="\\"),
                    Installer.base_postcode.ilike(pattern, escape="\\"),
                    Installer.town.ilike(pattern, escape="\\"),
                    Installer.contact_email.ilike(pattern, escape="\\"),
                )
            )
            .order_by(Installer.business_name)
            .limit(_HITS_PER_KIND)
        )
        hits += [
            SearchHit(
                kind="installer",
                id=str(installer.id),
                title=installer.business_name,
                subtitle=f"{installer.town} · {installer.base_postcode}",
                href=f"/installers?open={installer.id}",
            )
            for installer in found
        ]
    if "leads" in access:
        found = await session.scalars(
            select(QuoteRequest)
            .where(
                or_(
                    QuoteRequest.reference.ilike(pattern, escape="\\"),
                    QuoteRequest.postcode.ilike(pattern, escape="\\"),
                    QuoteRequest.first_name.ilike(pattern, escape="\\"),
                    QuoteRequest.email.ilike(pattern, escape="\\"),
                )
            )
            .order_by(QuoteRequest.created_at.desc())
            .limit(_HITS_PER_KIND)
        )
        hits += [
            SearchHit(
                kind="lead",
                id=str(quote.id),
                title=f"{quote.first_name} · {quote.reference}",
                subtitle=f"{quote.postcode} · {quote.created_at:%d %b %Y}",
                href=f"/leads?open={quote.id}",
            )
            for quote in found
        ]
    if "locations" in access:
        found = await session.scalars(
            select(Location)
            .where(
                or_(
                    Location.name.ilike(pattern, escape="\\"),
                    Location.slug.ilike(pattern, escape="\\"),
                )
            )
            .order_by(Location.name)
            .limit(_HITS_PER_KIND)
        )
        hits += [
            SearchHit(
                kind="location",
                id=location.slug,
                title=location.name,
                subtitle=f"{location.region} · {'Live' if location.is_published else 'Draft'}",
                href=f"/locations?open={location.slug}",
            )
            for location in found
        ]
    if "messages" in access:
        found = await session.scalars(
            select(Conversation)
            .where(
                or_(
                    Conversation.homeowner_name.ilike(pattern, escape="\\"),
                    Conversation.homeowner_email.ilike(pattern, escape="\\"),
                )
            )
            .order_by(Conversation.last_message_at.desc())
            .limit(_HITS_PER_KIND)
        )
        hits += [
            SearchHit(
                kind="conversation",
                id=str(conversation.id),
                title=conversation.homeowner_name,
                subtitle=conversation.homeowner_email,
                href=f"/messages/{conversation.id}",
            )
            for conversation in found
        ]
    return SearchResults(query=term, hits=hits)


async def quote_progress(session: AsyncSession, quote_ids: list) -> dict:
    """`{quote_id: (installers matched, quotes sent, stage)}` for a page of requests."""
    if not quote_ids:
        return {}
    rows = await session.execute(
        select(
            QuoteRequest.id,
            lead_stats.installers_matched(),
            lead_stats.quotes_sent(),
            lead_stats.stage(),
        ).where(QuoteRequest.id.in_(quote_ids))
    )
    return {quote_id: (matched or 0, sent or 0, stage) for quote_id, matched, sent, stage in rows}
