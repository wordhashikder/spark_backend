"""Free basic listings: content batches, unclaimed listings and the claim flow."""

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.enums import InstallerSource, InstallerStatus, Plan, Role
from app.models import BlogPost, Installer, QuoteMatch, SeedBatch, User
from app.services import seeding
from tests.helpers import Fakes, auth_headers, create_installer, create_user, quote_payload

NEW_PASSWORD = "Another-s3cret-pass"


async def _imported_listing(db: AsyncSession, name: str = "Spark Bros Electrical") -> Installer:
    installer = await create_installer(db, name)
    user = installer.user
    installer.user = None
    installer.plan = Plan.FREE
    installer.source = InstallerSource.IMPORTED
    installer.contact_email = "office@sparkbros.co.uk"
    await db.flush()
    await db.delete(user)
    await db.commit()
    return installer


async def test_content_batches_are_applied_once(db: AsyncSession):
    first = await seeding.seed_content(db)
    names = [name for name, _ in first]
    assert names[:2] == ["blog-articles-2026-10", "directory-listings-2026-10"]
    listings = dict(first)["directory-listings-2026-10"]
    assert listings == 193

    imported = await db.scalar(
        select(func.count())
        .select_from(Installer)
        .where(Installer.source == InstallerSource.IMPORTED, Installer.user_id.is_(None))
    )
    assert imported >= 193
    sample = await db.scalar(select(Installer).where(Installer.contact_email.is_not(None)).limit(1))
    assert (sample.status, sample.plan, sample.is_claimed) == (
        InstallerStatus.APPROVED,
        Plan.FREE,
        False,
    )

    # Deleted content is never re-added: a batch runs once, ever.
    await db.execute(BlogPost.__table__.delete())
    await db.commit()
    assert await seeding.seed_content(db) == []
    assert await db.scalar(select(func.count()).select_from(BlogPost)) == 0
    assert await db.scalar(select(func.count()).select_from(SeedBatch)) == len(first)


async def test_unclaimed_listing_is_public_but_gets_no_leads(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    listing = await _imported_listing(db)
    listing.plan = Plan.PRO  # even on a paid plan, a listing without an account gets no leads
    await db.commit()

    profile = await client.get(f"/api/v1/installers/{listing.slug}")
    assert profile.status_code == 200
    cards = (await client.get("/api/v1/installers")).json()["items"]
    card = next(item for item in cards if item["slug"] == listing.slug)
    assert (card["is_claimed"], card["verified"]) == (False, False)

    await client.post("/api/v1/quotes", json=quote_payload())
    assert await db.scalar(select(func.count()).select_from(QuoteMatch)) == 0

    await client.post(
        f"/api/v1/installers/{listing.slug}/enquiries",
        json={"name": "Sam", "email": "sam@example.com", "message": "Please quote for a charger."},
    )
    team = fakes.emails.of("enquiry_for_team")[-1]
    assert team.context["installer_email"] == "office@sparkbros.co.uk"
    assert team.context["claimed"] is False


async def test_business_claims_its_listing_with_the_email_on_file(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    listing = await _imported_listing(db)

    response = await client.post(
        f"/api/v1/installers/{listing.slug}/claim", json={"email": "Office@SparkBros.co.uk"}
    )
    assert response.status_code == 202
    token = fakes.emails.token_from("listing_claim")
    assert fakes.emails.of("listing_claim")[-1].to == "office@sparkbros.co.uk"

    preview = await client.get("/api/v1/auth/claim", params={"token": token})
    assert preview.json()["business_name"] == "Spark Bros Electrical"

    claimed = await client.post(
        "/api/v1/auth/claim", json={"token": token, "password": NEW_PASSWORD, "accept_terms": True}
    )
    assert claimed.status_code == 200, claimed.text

    await db.refresh(listing)
    assert listing.is_claimed
    assert listing.claimed_at is not None
    login = await client.post(
        "/api/v1/auth/login", json={"email": "office@sparkbros.co.uk", "password": NEW_PASSWORD}
    )
    assert login.status_code == 200
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert me.json()["installer"]["slug"] == listing.slug

    # The link works once.
    again = await client.post(
        "/api/v1/auth/claim", json={"token": token, "password": NEW_PASSWORD, "accept_terms": True}
    )
    assert again.json()["error"]["code"] == "listing_already_claimed"


async def test_claim_from_another_email_goes_to_the_team(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    listing = await _imported_listing(db)
    response = await client.post(
        f"/api/v1/installers/{listing.slug}/claim", json={"email": "someone@example.com"}
    )
    assert response.status_code == 202
    assert fakes.emails.of("listing_claim") == []
    review = fakes.emails.of("claim_needs_review")[-1]
    assert (review.to, review.reply_to) == ("support@pickasparky.test", "someone@example.com")


async def test_bad_or_tampered_claim_tokens_are_refused(
    client: httpx.AsyncClient, db: AsyncSession
):
    listing = await _imported_listing(db)
    wrong_email = security.create_listing_claim_token(listing.id, "attacker@evil.test")
    for token in ("not-a-token", wrong_email):
        response = await client.post(
            "/api/v1/auth/claim",
            json={"token": token, "password": NEW_PASSWORD, "accept_terms": True},
        )
        assert response.json()["error"]["code"] == "invalid_token"
    assert not (await db.get(Installer, listing.id)).is_claimed


async def test_admin_sends_claim_invites_and_edits_the_claim_email(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    admin = await create_user(db, role=Role.ADMIN)
    listing = await _imported_listing(db)
    headers = auth_headers(admin)

    found = await client.get(
        "/api/v1/admin/installers", params={"q": "spark bros", "claimed": "false"}, headers=headers
    )
    assert [item["slug"] for item in found.json()["items"]] == [listing.slug]
    assert found.json()["items"][0]["email"] == "office@sparkbros.co.uk"

    updated = await client.patch(
        f"/api/v1/admin/installers/{listing.id}",
        json={"contact_email": "owner@sparkbros.co.uk"},
        headers=headers,
    )
    assert updated.json()["email"] == "owner@sparkbros.co.uk"

    invite = await client.post(
        f"/api/v1/admin/installers/{listing.id}/claim-invite", headers=headers
    )
    assert invite.status_code == 202
    sent = fakes.emails.of("listing_claim")[-1]
    assert (sent.to, sent.context["invited"]) == ("owner@sparkbros.co.uk", True)

    claimed_one = await create_installer(db, "Already Claimed")
    refused = await client.post(
        f"/api/v1/admin/installers/{claimed_one.id}/claim-invite", headers=headers
    )
    assert refused.json()["error"]["code"] == "listing_already_claimed"


async def test_deleting_an_account_keeps_its_listing(db: AsyncSession):
    installer = await create_installer(db, "Keeps Listing")
    await db.delete(await db.get(User, installer.user_id))
    await db.commit()
    kept = await db.execute(select(Installer.user_id).where(Installer.id == installer.id))
    assert kept.one() == (None,)
