"""Installer directory (public), direct enquiries, and the signed-in installer's own profile,
media, leads and enquiries."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.api.deps import (
    ClientIpDep,
    EmailQueueDep,
    GeocoderDep,
    InstallerDep,
    PageDep,
    SessionDep,
    StorageDep,
    read_upload,
)
from app.core.plans import capabilities_for
from app.core.rate_limit import rate_limit
from app.schemas.common import Message, Paginated
from app.schemas.enquiry import Enquiry, EnquiryCreate
from app.schemas.installer import (
    InstallerCard,
    InstallerDetail,
    InstallerProfile,
    InstallerUpdate,
    Photo,
)
from app.schemas.quote import Lead, LeadUpdate
from app.schemas.review import ReviewOut
from app.services import enquiries, installers, leads, reviews

router = APIRouter(prefix="/installers", tags=["installers"])

_DEFAULT_SIMILAR = 4
_ENQUIRY_SENT = "Your request has been sent. We've emailed you a copy."


@router.get("")
async def list_installers(
    session: SessionDep,
    page: PageDep,
    location: Annotated[str | None, Query(max_length=80)] = None,
    featured: bool | None = None,
) -> Paginated[InstallerCard]:
    found, total = await installers.list_public(
        session, location_slug=location, featured=featured, offset=page.offset, limit=page.page_size
    )
    return Paginated.build(
        [InstallerCard.from_installer(installer) for installer in found],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/me")
async def get_own_profile(installer: InstallerDep) -> InstallerProfile:
    return InstallerProfile.from_installer(installer)


@router.patch("/me")
async def update_own_profile(
    data: InstallerUpdate, installer: InstallerDep, session: SessionDep, geocoder: GeocoderDep
) -> InstallerProfile:
    updated = await installers.update_profile(session, installer, data, geocoder)
    return InstallerProfile.from_installer(updated)


@router.post("/me/logo")
async def upload_logo(
    installer: InstallerDep,
    session: SessionDep,
    storage: StorageDep,
    file: Annotated[UploadFile, File()],
) -> InstallerProfile:
    updated = await installers.set_logo(session, installer, await read_upload(file), storage)
    return InstallerProfile.from_installer(updated)


@router.post("/me/photos", status_code=status.HTTP_201_CREATED)
async def upload_photo(
    installer: InstallerDep,
    session: SessionDep,
    storage: StorageDep,
    file: Annotated[UploadFile, File()],
    alt: Annotated[str | None, Form(max_length=160)] = None,
) -> Photo:
    photo = await installers.add_photo(
        session, installer, await read_upload(file), (alt or "").strip() or None, storage
    )
    return Photo.model_validate(photo)


@router.delete("/me/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_photo(
    photo_id: uuid.UUID, installer: InstallerDep, session: SessionDep, storage: StorageDep
) -> None:
    await installers.delete_photo(session, installer, photo_id, storage)


@router.get("/me/leads")
async def list_leads(
    installer: InstallerDep, session: SessionDep, page: PageDep
) -> Paginated[Lead]:
    found, total = await leads.list_for_installer(
        session, installer, offset=page.offset, limit=page.page_size
    )
    reveal_contact = capabilities_for(installer.plan).receives_leads
    return Paginated.build(
        [Lead.from_match(lead, reveal_contact=reveal_contact) for lead in found],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.patch("/me/leads/{lead_id}")
async def update_lead(
    lead_id: uuid.UUID,
    data: LeadUpdate,
    installer: InstallerDep,
    session: SessionDep,
    emails: EmailQueueDep,
) -> Lead:
    lead, outbox = await leads.update_status(session, installer, lead_id, data.status)
    emails.send(outbox)
    return Lead.from_match(lead, reveal_contact=capabilities_for(installer.plan).receives_leads)


@router.get("/me/enquiries")
async def list_enquiries(
    installer: InstallerDep, session: SessionDep, page: PageDep
) -> Paginated[Enquiry]:
    found, total = await enquiries.list_for_installer(
        session, installer, offset=page.offset, limit=page.page_size
    )
    return Paginated.build(
        [Enquiry.model_validate(enquiry) for enquiry in found],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.post(
    "/{slug}/enquiries",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("enquiries", "10/hour"))],
)
async def send_enquiry(
    slug: str,
    data: EnquiryCreate,
    session: SessionDep,
    client_ip: ClientIpDep,
    emails: EmailQueueDep,
) -> Message:
    """The "Request a Quote" form on a profile.

    Pro and Premium installers receive the request themselves; requests to Free-plan
    installers go to the PickASparky team. Either way the customer is emailed a copy.
    """
    if not data.website:  # a filled honeypot gets the same answer, and nothing is stored
        emails.send(await enquiries.create(session, slug, data, client_ip))
    return Message(message=_ENQUIRY_SENT)


@router.get("/{slug}")
async def get_installer(slug: str, session: SessionDep) -> InstallerDetail:
    return InstallerDetail.from_installer(await installers.get_public(session, slug))


@router.get("/{slug}/reviews")
async def list_installer_reviews(
    slug: str, session: SessionDep, page: PageDep
) -> Paginated[ReviewOut]:
    found, total = await reviews.list_for_installer(
        session, slug, offset=page.offset, limit=page.page_size
    )
    return Paginated.build(
        [ReviewOut.model_validate(review) for review in found],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/{slug}/similar")
async def list_similar_installers(
    slug: str,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=installers.MAX_SIMILAR)] = _DEFAULT_SIMILAR,
) -> list[InstallerCard]:
    similar = await installers.list_similar(session, slug, limit)
    return [InstallerCard.from_installer(installer) for installer in similar]
