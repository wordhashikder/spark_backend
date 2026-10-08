"""Back-office endpoints (admin role only)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.api.deps import EmailQueueDep, PageDep, SessionDep, StorageDep, read_upload, require_role
from app.core.enums import (
    AccreditationScheme,
    BlogPostStatus,
    InstallerStatus,
    ReviewStatus,
    Role,
)
from app.schemas.admin import (
    AccreditationVerification,
    AdminContactMessage,
    AdminInstaller,
    AdminInstallerUpdate,
    AdminQuote,
    AdminReview,
    AdminReviewUpdate,
)
from app.schemas.blog import AdminBlogPost, BlogPostCreate, BlogPostUpdate
from app.schemas.common import Paginated
from app.schemas.enquiry import AdminEnquiry
from app.schemas.location import AdminLocation, AdminLocationUpdate
from app.services import admin, blog, enquiries, locations

AltForm = Annotated[str | None, Form(max_length=160)]

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


@router.get("/enquiries")
async def list_enquiries(session: SessionDep, page: PageDep) -> Paginated[AdminEnquiry]:
    """Direct requests sent to installers from their profile pages."""
    found, total = await enquiries.list_all(session, offset=page.offset, limit=page.page_size)
    return Paginated.build(
        [AdminEnquiry.from_enquiry(enquiry) for enquiry in found],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


# ---- Locations: intro and photo --------------------------------------------------------


@router.get("/locations")
async def list_locations(session: SessionDep) -> list[AdminLocation]:
    return [
        AdminLocation.model_validate(location) for location in await locations.list_all(session)
    ]


@router.patch("/locations/{slug}")
async def update_location(
    slug: str, data: AdminLocationUpdate, session: SessionDep, storage: StorageDep
) -> AdminLocation:
    """Edit the intro, or point the photo at a URL (an https:// address or a site path)."""
    location = await locations.update_content(session, slug, data, storage)
    return AdminLocation.model_validate(location)


@router.post("/locations/{slug}/image")
async def upload_location_image(
    slug: str,
    session: SessionDep,
    storage: StorageDep,
    file: Annotated[UploadFile, File()],
    alt: AltForm = None,
    credit: AltForm = None,
) -> AdminLocation:
    """Upload the photo shown under "Powering a greener {town}" (JPEG, PNG or WebP, 5 MB)."""
    location = await locations.set_image(
        session,
        slug,
        await read_upload(file),
        storage,
        alt=(alt or "").strip() or None,
        credit=(credit or "").strip() or None,
    )
    return AdminLocation.model_validate(location)


@router.delete("/locations/{slug}/image")
async def delete_location_image(
    slug: str, session: SessionDep, storage: StorageDep
) -> AdminLocation:
    """Remove the photo; the page shows its generated local map instead."""
    return AdminLocation.model_validate(await locations.remove_image(session, slug, storage))


# ---- Blog ----------------------------------------------------------------------------


@router.get("/blog/posts")
async def list_blog_posts(
    session: SessionDep, page: PageDep, status: BlogPostStatus | None = None
) -> Paginated[AdminBlogPost]:
    found, total = await blog.list_all(
        session, status=status, offset=page.offset, limit=page.page_size
    )
    return Paginated.build(
        [AdminBlogPost.model_validate(post) for post in found],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.post("/blog/posts", status_code=status.HTTP_201_CREATED)
async def create_blog_post(data: BlogPostCreate, session: SessionDep) -> AdminBlogPost:
    return AdminBlogPost.model_validate(await blog.create(session, data))


@router.get("/blog/posts/{post_id}")
async def get_blog_post(post_id: uuid.UUID, session: SessionDep) -> AdminBlogPost:
    return AdminBlogPost.model_validate(await blog.get(session, post_id))


@router.patch("/blog/posts/{post_id}")
async def update_blog_post(
    post_id: uuid.UUID, data: BlogPostUpdate, session: SessionDep, storage: StorageDep
) -> AdminBlogPost:
    return AdminBlogPost.model_validate(await blog.update(session, post_id, data, storage))


@router.delete("/blog/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blog_post(post_id: uuid.UUID, session: SessionDep, storage: StorageDep) -> None:
    await blog.delete(session, post_id, storage)


@router.post("/blog/posts/{post_id}/cover")
async def upload_blog_cover(
    post_id: uuid.UUID,
    session: SessionDep,
    storage: StorageDep,
    file: Annotated[UploadFile, File()],
    alt: AltForm = None,
) -> AdminBlogPost:
    """Upload the cover image (JPEG, PNG or WebP, 5 MB); it replaces the current one."""
    post = await blog.set_cover(
        session, post_id, await read_upload(file), (alt or "").strip() or None, storage
    )
    return AdminBlogPost.model_validate(post)


@router.delete("/blog/posts/{post_id}/cover")
async def delete_blog_cover(
    post_id: uuid.UUID, session: SessionDep, storage: StorageDep
) -> AdminBlogPost:
    return AdminBlogPost.model_validate(await blog.remove_cover(session, post_id, storage))
