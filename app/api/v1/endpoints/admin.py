"""Back-office endpoints for the PickASparky team.

Every route checks the signed-in team member's staff role against the role matrix (see
`require_admin_access` and `app/core/permissions.py`). Changes that show on the public
website refresh its cached pages straight away (`CacheRefreshDep`).
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.api.deps import (
    AccessDep,
    CacheRefreshDep,
    EmailQueueDep,
    GeocoderDep,
    PageDep,
    PlatformSettingsDep,
    SessionDep,
    SettingsDep,
    StaffDep,
    StorageDep,
    read_upload,
    require_admin_access,
)
from app.core.enums import (
    AccreditationScheme,
    BlogPostStatus,
    InstallerSource,
    InstallerStatus,
    Plan,
    QuoteStatus,
    ReviewStatus,
)
from app.schemas.admin import (
    AccreditationVerification,
    AdminContactMessage,
    AdminInstaller,
    AdminInstallerCreate,
    AdminInstallerUpdate,
    AdminOverview,
    AdminQuote,
    AdminQuoteMatch,
    AdminReview,
    AdminReviewUpdate,
    AdminSettings,
    ImportReport,
    MediaUpload,
    NavCounts,
    QuoteAssign,
    QuoteCandidate,
    SearchResults,
    StageCounts,
    TeamMessageCreate,
)
from app.schemas.blog import AdminBlogPost, BlogPostCreate, BlogPostUpdate
from app.schemas.common import Message, Paginated
from app.schemas.content import ContentDocument, ContentRevision, ContentSummary, ContentUpdate
from app.schemas.conversation import ConversationDetail, ConversationSummary, MessageOut
from app.schemas.enquiry import AdminEnquiry
from app.schemas.location import AdminLocation, AdminLocationCreate, AdminLocationUpdate
from app.schemas.team import (
    InviteCreate,
    RoleMatrix,
    RoleMatrixUpdate,
    TeamMember,
    TeamMemberUpdate,
)
from app.services import (
    admin,
    blog,
    claims,
    content,
    conversations,
    enquiries,
    insights,
    installer_import,
    lead_stats,
    locations,
    platform,
    team,
)
from app.services.storage import validate_image

AltForm = Annotated[str | None, Form(max_length=160)]
SearchQuery = Annotated[str | None, Query(max_length=100)]

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_access)])

# Website cache tags (see the website's `src/lib/api.ts`).
_INSTALLER_PAGES = ("installers", "locations")
_LOCATION_PAGES = ("locations",)


# ---- Overview, sidebar badges and global search -----------------------------------------


@router.get("/overview")
async def overview(
    session: SessionDep,
    platform_settings: PlatformSettingsDep,
    days: Annotated[int, Query(ge=7, le=365)] = 30,
) -> AdminOverview:
    return await insights.overview(
        session, days=days, max_installers=platform_settings.lead_matching.max_installers
    )


@router.get("/nav")
async def nav_counts(session: SessionDep, access: AccessDep) -> NavCounts:
    """Badges for the sidebar (only for the modules the member may use)."""
    return await insights.nav_counts(session, access)


@router.get("/search")
async def search(
    session: SessionDep, access: AccessDep, q: Annotated[str, Query(max_length=100)] = ""
) -> SearchResults:
    """Installers, leads, locations and conversations matching `q` (top bar search)."""
    return await insights.search(session, q, access)


# ---- Settings, team and roles -----------------------------------------------------------


@router.get("/settings")
async def get_settings(session: SessionDep, settings: SettingsDep) -> AdminSettings:
    return AdminSettings(
        settings=await platform.load(session, fresh=True),
        status=admin.platform_status(settings),
    )


@router.put("/settings")
async def save_settings(
    data: platform.PlatformSettingsUpdate,
    session: SessionDep,
    settings: SettingsDep,
    user: StaffDep,
    refresh: CacheRefreshDep,
) -> AdminSettings:
    saved = await platform.save(session, data, user)
    # The organisation's name and email appear on the website.
    refresh("content")
    return AdminSettings(settings=saved, status=admin.platform_status(settings))


@router.get("/roles")
async def role_matrix(session: SessionDep) -> RoleMatrix:
    return await team.matrix(session)


@router.put("/roles")
async def update_role_matrix(
    data: RoleMatrixUpdate, session: SessionDep, user: StaffDep
) -> RoleMatrix:
    """Change which modules each role may use (owners only; owners keep everything)."""
    return await team.update_matrix(session, user, data.access)


@router.get("/team")
async def list_team(session: SessionDep, user: StaffDep) -> list[TeamMember]:
    return await team.list_members(session, user)


@router.post("/team", status_code=status.HTTP_201_CREATED)
async def invite_member(
    data: InviteCreate, session: SessionDep, user: StaffDep, emails: EmailQueueDep
) -> TeamMember:
    """Invite someone to the team: they get an email link to set their password."""
    member, outbox = await team.invite(session, user, data)
    emails.send(outbox)
    return member


@router.patch("/team/{member_id}")
async def update_member(
    member_id: uuid.UUID, data: TeamMemberUpdate, session: SessionDep, user: StaffDep
) -> TeamMember:
    return await team.update_member(session, user, member_id, data)


@router.post("/team/{member_id}/resend", status_code=status.HTTP_202_ACCEPTED)
async def resend_invite(
    member_id: uuid.UUID, session: SessionDep, user: StaffDep, emails: EmailQueueDep
) -> TeamMember:
    member, outbox = await team.resend_invite(session, user, member_id)
    emails.send(outbox)
    return member


@router.delete("/team/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw_invite(member_id: uuid.UUID, session: SessionDep, user: StaffDep) -> None:
    """Withdraw an invitation nobody has accepted yet."""
    await team.remove_invite(session, user, member_id)


# ---- Website content ----------------------------------------------------------------------


@router.get("/content")
async def list_content(session: SessionDep) -> list[ContentSummary]:
    return await content.list_documents(session)


@router.get("/content/{key}", response_model_by_alias=True)
async def get_content(key: str, session: SessionDep) -> ContentDocument:
    return await content.get_for_editing(session, key)


@router.put("/content/{key}")
async def save_content(
    key: str, data: ContentUpdate, session: SessionDep, user: StaffDep, refresh: CacheRefreshDep
) -> ContentDocument:
    """Publish the page's content; the website shows it within seconds."""
    saved = await content.save(session, key, data.content, user)
    refresh(*content.cache_tags(key))
    return saved


@router.delete("/content/{key}")
async def reset_content(
    key: str, session: SessionDep, user: StaffDep, refresh: CacheRefreshDep
) -> ContentDocument:
    """Back to the original wording (the edited version stays in the history)."""
    restored = await content.reset(session, key, user)
    refresh(*content.cache_tags(key))
    return restored


@router.get("/content/{key}/revisions")
async def list_content_revisions(key: str, session: SessionDep) -> list[ContentRevision]:
    return await content.revisions(session, key)


@router.post("/content/{key}/revisions/{revision_id}/restore")
async def restore_content_revision(
    key: str,
    revision_id: uuid.UUID,
    session: SessionDep,
    user: StaffDep,
    refresh: CacheRefreshDep,
) -> ContentDocument:
    restored = await content.restore(session, key, revision_id, user)
    refresh(*content.cache_tags(key))
    return restored


@router.post("/media", status_code=status.HTTP_201_CREATED)
async def upload_media(storage: StorageDep, file: Annotated[UploadFile, File()]) -> MediaUpload:
    """Upload an image for page content (JPEG, PNG or WebP, 5 MB); returns its URL."""
    data = await read_upload(file)
    validate_image(data)
    stored = await storage.upload(data, folder="content")
    return MediaUpload(url=stored.url)


# ---- Installers ---------------------------------------------------------------------------


@router.get("/installers")
async def list_installers(
    session: SessionDep,
    page: PageDep,
    status: InstallerStatus | None = None,
    source: InstallerSource | None = None,
    plan: Plan | None = None,
    claimed: bool | None = None,
    q: SearchQuery = None,
) -> Paginated[AdminInstaller]:
    found, total = await admin.list_installers(
        session,
        status=status,
        source=source,
        plan=plan,
        claimed=claimed,
        search=q,
        offset=page.offset,
        limit=page.page_size,
    )
    return Paginated.build(
        [AdminInstaller.from_installer(installer) for installer in found],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.post("/installers", status_code=status.HTTP_201_CREATED)
async def create_installer(
    data: AdminInstallerCreate,
    session: SessionDep,
    geocoder: GeocoderDep,
    refresh: CacheRefreshDep,
) -> AdminInstaller:
    """Add a listing. It has no account until the business claims it."""
    installer = await admin.create_installer(session, data, geocoder)
    refresh(*_INSTALLER_PAGES)
    return AdminInstaller.from_installer(installer)


@router.post("/installers/import")
async def import_installers(
    session: SessionDep,
    geocoder: GeocoderDep,
    refresh: CacheRefreshDep,
    file: Annotated[UploadFile, File()],
    dry_run: Annotated[bool, Form()] = True,
) -> ImportReport:
    """Add listings from a CSV file. `dry_run` (the default) checks without saving."""
    report = await installer_import.import_csv(
        session, await file.read(installer_import.MAX_BYTES + 1), geocoder, dry_run=dry_run
    )
    if not dry_run and report.created:
        refresh(*_INSTALLER_PAGES)
    return report


@router.get("/installers/{installer_id}")
async def get_installer(installer_id: uuid.UUID, session: SessionDep) -> AdminInstaller:
    return AdminInstaller.from_installer(await admin.get_installer(session, installer_id))


@router.post("/installers/{installer_id}/claim-invite", status_code=status.HTTP_202_ACCEPTED)
async def send_claim_invite(
    installer_id: uuid.UUID, session: SessionDep, emails: EmailQueueDep
) -> Message:
    """Email an unclaimed listing the link to claim it (to the email on file)."""
    installer = await admin.get_installer(session, installer_id)
    emails.send(await claims.invite(session, installer))
    return Message(message=f"Claim invitation sent to {installer.contact_email}.")


@router.patch("/installers/{installer_id}")
async def update_installer(
    installer_id: uuid.UUID,
    data: AdminInstallerUpdate,
    session: SessionDep,
    emails: EmailQueueDep,
    geocoder: GeocoderDep,
    refresh: CacheRefreshDep,
) -> AdminInstaller:
    installer, outbox = await admin.update_installer(session, installer_id, data, geocoder)
    emails.send(outbox)
    refresh(*_INSTALLER_PAGES)
    return AdminInstaller.from_installer(installer)


@router.patch("/installers/{installer_id}/accreditations/{scheme}")
async def verify_accreditation(
    installer_id: uuid.UUID,
    scheme: AccreditationScheme,
    data: AccreditationVerification,
    session: SessionDep,
    refresh: CacheRefreshDep,
) -> AdminInstaller:
    installer = await admin.set_accreditation_verified(session, installer_id, scheme, data.verified)
    refresh("installers")
    return AdminInstaller.from_installer(installer)


# ---- Reviews ------------------------------------------------------------------------------


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
    review_id: uuid.UUID, data: AdminReviewUpdate, session: SessionDep, refresh: CacheRefreshDep
) -> AdminReview:
    review = await admin.moderate_review(session, review_id, data.status)
    refresh("reviews", "installers")
    return AdminReview.from_review(review)


# ---- Leads & quotes -----------------------------------------------------------------------


@router.get("/quotes")
async def list_quotes(
    session: SessionDep,
    page: PageDep,
    platform_settings: PlatformSettingsDep,
    status: QuoteStatus | None = None,
    stage: lead_stats.Stage | None = None,
    q: SearchQuery = None,
) -> Paginated[AdminQuote]:
    found, total = await admin.list_quotes(
        session, status=status, stage=stage, search=q, offset=page.offset, limit=page.page_size
    )
    return Paginated.build(
        [
            AdminQuote.model_validate(quote).model_copy(
                update={
                    "installers_matched": matched,
                    "quotes_sent": sent,
                    "stage": stage,
                    "max_installers": platform_settings.lead_matching.max_installers,
                }
            )
            for quote, matched, sent, stage in found
        ],
        total=total,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/quotes/stages")
async def quote_stages(session: SessionDep) -> StageCounts:
    """How many requests are open, awaiting a decision, closed, or held for the team."""
    return StageCounts(**await admin.stage_counts(session))


@router.get("/quotes/{quote_id}")
async def get_quote(
    quote_id: uuid.UUID, session: SessionDep, platform_settings: PlatformSettingsDep
) -> AdminQuote:
    """One quote request with its progress (opened from search or a notification)."""
    quote = await admin.get_quote(session, quote_id)
    matched, sent, stage = (await insights.quote_progress(session, [quote.id]))[quote.id]
    return AdminQuote.model_validate(quote).model_copy(
        update={
            "installers_matched": matched,
            "quotes_sent": sent,
            "stage": stage,
            "max_installers": platform_settings.lead_matching.max_installers,
        }
    )


@router.get("/quotes/{quote_id}/matches")
async def list_quote_matches(quote_id: uuid.UUID, session: SessionDep) -> list[AdminQuoteMatch]:
    """The installers a quote request was sent to, and how far each has got."""
    return [
        AdminQuoteMatch.from_match(match) for match in await admin.quote_matches(session, quote_id)
    ]


@router.get("/quotes/{quote_id}/candidates")
async def list_quote_candidates(quote_id: uuid.UUID, session: SessionDep) -> list[QuoteCandidate]:
    """Installers the request could go to, those covering the address first."""
    return await admin.quote_candidates(session, quote_id)


@router.post("/quotes/{quote_id}/assign")
async def assign_quote(
    quote_id: uuid.UUID,
    data: QuoteAssign,
    session: SessionDep,
    emails: EmailQueueDep,
    platform_settings: PlatformSettingsDep,
) -> list[AdminQuoteMatch]:
    """Send the request to the chosen installers; they and the homeowner are emailed."""
    matches, outbox = await admin.assign_quote(
        session,
        quote_id,
        data.installer_ids,
        max_installers=platform_settings.lead_matching.max_installers,
    )
    emails.send(outbox)
    return [AdminQuoteMatch.from_match(match) for match in matches]


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


# ---- Messages -----------------------------------------------------------------------------


@router.get("/conversations")
async def list_conversations(
    session: SessionDep,
    page: PageDep,
    installer_id: uuid.UUID | None = None,
    kind: Literal["lead", "enquiry"] | None = None,
    q: SearchQuery = None,
) -> Paginated[ConversationSummary]:
    """Every conversation between installers and homeowners, latest activity first."""
    found, total = await conversations.list_all(
        session,
        installer_id=installer_id,
        kind=kind,
        search=q,
        offset=page.offset,
        limit=page.page_size,
    )
    return Paginated.build(found, total=total, page=page.page, page_size=page.page_size)


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: uuid.UUID, session: SessionDep) -> ConversationDetail:
    """A conversation's full history, quotes included."""
    return await conversations.get_any(session, conversation_id)


@router.post("/conversations/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
async def send_team_message(
    conversation_id: uuid.UUID,
    data: TeamMessageCreate,
    session: SessionDep,
    user: StaffDep,
    emails: EmailQueueDep,
) -> MessageOut:
    """Write into the conversation as the PickASparky team; both sides are emailed."""
    message, outbox = await conversations.team_message(session, user, conversation_id, data.body)
    emails.send(outbox)
    return message


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


# ---- SEO & locations ----------------------------------------------------------------------


@router.get("/locations")
async def list_locations(session: SessionDep) -> list[AdminLocation]:
    return [
        AdminLocation.model_validate(location).model_copy(update={"installer_count": count})
        for location, count in await locations.list_all_with_counts(session)
    ]


@router.post("/locations", status_code=status.HTTP_201_CREATED)
async def create_location(
    data: AdminLocationCreate,
    session: SessionDep,
    geocoder: GeocoderDep,
    refresh: CacheRefreshDep,
) -> AdminLocation:
    """Add a town page (a draft unless `is_published`)."""
    location = await locations.create(session, data, geocoder)
    if location.is_published:
        refresh(*_LOCATION_PAGES)
    return AdminLocation.model_validate(location)


@router.patch("/locations/{slug}")
async def update_location(
    slug: str,
    data: AdminLocationUpdate,
    session: SessionDep,
    storage: StorageDep,
    refresh: CacheRefreshDep,
) -> AdminLocation:
    """Edit the page: heading, text, search snippet, photo, address (drafts) or publish it."""
    location = await locations.update_content(session, slug, data, storage)
    refresh(*_LOCATION_PAGES)
    return AdminLocation.model_validate(location)


@router.post("/locations/{slug}/image")
async def upload_location_image(
    slug: str,
    session: SessionDep,
    storage: StorageDep,
    refresh: CacheRefreshDep,
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
    refresh(*_LOCATION_PAGES)
    return AdminLocation.model_validate(location)


@router.delete("/locations/{slug}/image")
async def delete_location_image(
    slug: str, session: SessionDep, storage: StorageDep, refresh: CacheRefreshDep
) -> AdminLocation:
    """Remove the photo; the page shows its generated local map instead."""
    location = await locations.remove_image(session, slug, storage)
    refresh(*_LOCATION_PAGES)
    return AdminLocation.model_validate(location)


# ---- Blog ---------------------------------------------------------------------------------


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
async def create_blog_post(
    data: BlogPostCreate, session: SessionDep, refresh: CacheRefreshDep
) -> AdminBlogPost:
    post = await blog.create(session, data)
    refresh("blog")
    return AdminBlogPost.model_validate(post)


@router.get("/blog/posts/{post_id}")
async def get_blog_post(post_id: uuid.UUID, session: SessionDep) -> AdminBlogPost:
    return AdminBlogPost.model_validate(await blog.get(session, post_id))


@router.patch("/blog/posts/{post_id}")
async def update_blog_post(
    post_id: uuid.UUID,
    data: BlogPostUpdate,
    session: SessionDep,
    storage: StorageDep,
    refresh: CacheRefreshDep,
) -> AdminBlogPost:
    post = await blog.update(session, post_id, data, storage)
    refresh("blog")
    return AdminBlogPost.model_validate(post)


@router.delete("/blog/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blog_post(
    post_id: uuid.UUID, session: SessionDep, storage: StorageDep, refresh: CacheRefreshDep
) -> None:
    await blog.delete(session, post_id, storage)
    refresh("blog")


@router.post("/blog/posts/{post_id}/cover")
async def upload_blog_cover(
    post_id: uuid.UUID,
    session: SessionDep,
    storage: StorageDep,
    refresh: CacheRefreshDep,
    file: Annotated[UploadFile, File()],
    alt: AltForm = None,
) -> AdminBlogPost:
    """Upload the cover image (JPEG, PNG or WebP, 5 MB); it replaces the current one."""
    post = await blog.set_cover(
        session, post_id, await read_upload(file), (alt or "").strip() or None, storage
    )
    refresh("blog")
    return AdminBlogPost.model_validate(post)


@router.delete("/blog/posts/{post_id}/cover")
async def delete_blog_cover(
    post_id: uuid.UUID, session: SessionDep, storage: StorageDep, refresh: CacheRefreshDep
) -> AdminBlogPost:
    post = await blog.remove_cover(session, post_id, storage)
    refresh("blog")
    return AdminBlogPost.model_validate(post)
