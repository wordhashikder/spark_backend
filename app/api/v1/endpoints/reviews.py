"""Featured reviews and invitation-based review submission."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import SessionDep
from app.core.rate_limit import rate_limit
from app.schemas.common import Message
from app.schemas.review import ReviewCreate, ReviewInvite, ReviewOut
from app.services import reviews

router = APIRouter(prefix="/reviews", tags=["reviews"])

_DEFAULT_FEATURED = 10


@router.get("/featured")
async def featured_reviews(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=reviews.MAX_FEATURED)] = _DEFAULT_FEATURED,
) -> list[ReviewOut]:
    featured = await reviews.list_featured(session, limit)
    return [ReviewOut.model_validate(review) for review in featured]


@router.get("/invite")
async def review_invitation(
    session: SessionDep, token: Annotated[str, Query(min_length=1, max_length=2048)]
) -> ReviewInvite:
    installer = await reviews.get_invitation(session, token)
    return ReviewInvite(installer_name=installer.business_name, installer_slug=installer.slug)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("review-submit", "5/hour"))],
)
async def submit_review(data: ReviewCreate, session: SessionDep) -> Message:
    await reviews.submit(session, data)
    return Message(message="Thank you. Your review will appear once it has been checked.")
