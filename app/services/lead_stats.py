"""SQL building blocks describing how far each quote request has got.

A request moves through three stages the back office shows as badges:

- **open**: no installer has sent a quote yet (including requests held for the team or
  that matched nobody);
- **awaiting**: at least one quote has been sent and the homeowner has not accepted one;
- **closed**: the homeowner accepted a quote, or an installer marked the job as won.
"""

from typing import Literal

from sqlalchemy import ColumnElement, and_, case, exists, func, not_, select

from app.core.enums import LeadStatus, OfferStatus
from app.models import Conversation, Offer, QuoteMatch, QuoteRequest

Stage = Literal["open", "awaiting", "closed"]


def _offers(*conditions: ColumnElement[bool], columns: tuple = (Offer.id,)):
    # Correlated to the outer query's quote request only, so these also work in queries
    # that select from `quote_matches` themselves (e.g. an installer's leads).
    return (
        select(*columns)
        .select_from(Offer)
        .join(Conversation, Conversation.id == Offer.conversation_id)
        .join(QuoteMatch, QuoteMatch.id == Conversation.quote_match_id)
        .where(QuoteMatch.quote_request_id == QuoteRequest.id, *conditions)
        .correlate(QuoteRequest)
    )


def is_closed() -> ColumnElement[bool]:
    accepted = exists(_offers(Offer.status == OfferStatus.ACCEPTED))
    won = exists(
        select(QuoteMatch.id)
        .where(QuoteMatch.quote_request_id == QuoteRequest.id, QuoteMatch.status == LeadStatus.WON)
        .correlate(QuoteRequest)
    )
    return accepted | won


def is_awaiting() -> ColumnElement[bool]:
    return and_(not_(is_closed()), exists(_offers(Offer.status == OfferStatus.SENT)))


def is_open() -> ColumnElement[bool]:
    return and_(not_(is_closed()), not_(exists(_offers(Offer.status == OfferStatus.SENT))))


def stage() -> ColumnElement[str]:
    return case((is_closed(), "closed"), (is_awaiting(), "awaiting"), else_="open")


def stage_filter(value: Stage) -> ColumnElement[bool]:
    return {"open": is_open, "awaiting": is_awaiting, "closed": is_closed}[value]()


def quotes_sent() -> ColumnElement[int]:
    """Quotes installers sent for the request (withdrawn ones excluded)."""
    return _offers(
        Offer.status != OfferStatus.WITHDRAWN, columns=(func.count(Offer.id),)
    ).scalar_subquery()


def installers_matched() -> ColumnElement[int]:
    return (
        select(func.count(QuoteMatch.id))
        .where(QuoteMatch.quote_request_id == QuoteRequest.id)
        .correlate(QuoteRequest)
        .scalar_subquery()
    )
