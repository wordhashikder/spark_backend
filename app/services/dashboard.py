"""Numbers for the installer's dashboard home."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import LeadStatus, OfferStatus
from app.core.plans import capabilities_for
from app.models import Installer, InstallerEnquiry, Offer, QuoteMatch
from app.schemas.conversation import InstallerSummary
from app.services import conversations


async def installer_summary(session: AsyncSession, installer: Installer) -> InstallerSummary:
    async def count(model: type, *filters) -> int:
        return await session.scalar(select(func.count()).select_from(model).where(*filters)) or 0

    own_lead = QuoteMatch.installer_id == installer.id
    own_offer = Offer.installer_id == installer.id
    return InstallerSummary(
        plan=installer.plan.value,
        receives_leads=capabilities_for(installer.plan).receives_leads,
        is_claimed=installer.is_claimed,
        status=installer.status.value,
        new_leads=await count(QuoteMatch, own_lead, QuoteMatch.status == LeadStatus.SENT),
        leads_total=await count(QuoteMatch, own_lead),
        enquiries_total=await count(
            InstallerEnquiry,
            InstallerEnquiry.installer_id == installer.id,
            InstallerEnquiry.sent_to_installer,
        ),
        unread_conversations=await conversations.count_unread_for_installer(session, installer),
        open_quotes=await count(Offer, own_offer, Offer.status == OfferStatus.SENT),
        accepted_quotes=await count(Offer, own_offer, Offer.status == OfferStatus.ACCEPTED),
        rating_avg=None if installer.rating_avg is None else float(installer.rating_avg),
        review_count=installer.review_count,
    )
