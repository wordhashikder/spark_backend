"""Back-office endpoints (admin role only)."""

import uuid

from fastapi import APIRouter, Depends

from app.api.deps import EmailQueueDep, PageDep, SessionDep, require_role
from app.core.enums import AccreditationScheme, InstallerStatus, ReviewStatus, Role
from app.schemas.admin import (
    AccreditationVerification,
    AdminContactMessage,
    AdminInstaller,
    AdminInstallerUpdate,
    AdminQuote,
    AdminReview,
    AdminReviewUpdate,
)
from app.schemas.common import Paginated
from app.services import admin

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_role(Role.ADMIN))]
)


@router.get("/installers")
async def list_installers(
    session: SessionDep, page: PageDep, status: InstallerStatus | None = None
) -> Paginated[AdminInstaller]:
    found, total = await admin.list_installers(
        session, status=status, offset=page.offset, limit=page.page_size
    )
    return Paginated.build(
        [AdminInstaller.from_installer(installer) for installer in found],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.patch("/installers/{installer_id}")
async def update_installer(
    installer_id: uuid.UUID,
    data: AdminInstallerUpdate,
    session: SessionDep,
    emails: EmailQueueDep,
) -> AdminInstaller:
    installer, outbox = await admin.update_installer(session, installer_id, data)
    emails.send(outbox)
    return AdminInstaller.from_installer(installer)


@router.patch("/installers/{installer_id}/accreditations/{scheme}")
async def verify_accreditation(
    installer_id: uuid.UUID,
    scheme: AccreditationScheme,
    data: AccreditationVerification,
    session: SessionDep,
) -> AdminInstaller:
    installer = await admin.set_accreditation_verified(session, installer_id, scheme, data.verified)
    return AdminInstaller.from_installer(installer)


@router.get("/reviews")
async def list_reviews(
    session: SessionDep, page: PageDep, status: ReviewStatus | None = None
) -> Paginated[AdminReview]:
    found, total = await admin.list_reviews(
        session, status=status, offset=page.offset, limit=page.page_size
    )
    return Paginated.build(
        [AdminReview.from_review(review) for review in found],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.patch("/reviews/{review_id}")
async def moderate_review(
    review_id: uuid.UUID, data: AdminReviewUpdate, session: SessionDep
) -> AdminReview:
    review = await admin.moderate_review(session, review_id, data.status)
    return AdminReview.from_review(review)


@router.get("/quotes")
async def list_quotes(session: SessionDep, page: PageDep) -> Paginated[AdminQuote]:
    found, total = await admin.list_quotes(session, offset=page.offset, limit=page.page_size)
    return Paginated.build(
        [AdminQuote.model_validate(quote) for quote in found],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/contact-messages")
async def list_contact_messages(
    session: SessionDep, page: PageDep
) -> Paginated[AdminContactMessage]:
    found, total = await admin.list_contact_messages(
        session, offset=page.offset, limit=page.page_size
    )
    return Paginated.build(
        [AdminContactMessage.model_validate(message) for message in found],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )
