"""Leads, review invitations, moderation and the back office."""

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.enums import InstallerStatus, Plan, ReviewStatus, Role
from app.models import Installer, QuoteMatch, Review
from tests.helpers import (
    Fakes,
    auth_headers,
    create_installer,
    create_review,
    create_user,
    quote_payload,
)

REVIEW = {
    "rating": 5,
    "title": "Great service from start to finish",
    "body": "Installed my charger quickly and professionally. Really happy with the service.",
    "author_name": "Steve M.",
    "author_location": "Manchester",
}


async def _lead_for(client: httpx.AsyncClient, db: AsyncSession, installer: Installer) -> str:
    """Submit a quote that matches `installer` and return the resulting lead id."""
    response = await client.post("/api/v1/quotes", json=quote_payload())
    assert response.status_code == 201
    lead = await db.scalar(select(QuoteMatch).where(QuoteMatch.installer_id == installer.id))
    return str(lead.id)


async def test_leads_show_contact_details_only_on_a_lead_receiving_plan(
    client: httpx.AsyncClient, db: AsyncSession
):
    installer = await create_installer(db, "Lead Taker")
    headers = auth_headers(installer.user)
    await _lead_for(client, db, installer)

    leads = (await client.get("/api/v1/installers/me/leads", headers=headers)).json()
    assert leads["total"] == 1
    quote = leads["items"][0]["quote"]
    assert leads["items"][0]["status"] == "sent"
    assert (quote["postcode"], quote["email"], quote["phone"]) == (
        "M1 1AA",
        "sam@example.com",
        "07700 900123",
    )
    assert quote["charger_followup"] == "installer_recommend"

    # After a downgrade the lead stays visible but the customer's details are withheld.
    installer.plan = Plan.FREE
    db.add(installer)
    await db.commit()
    downgraded = (await client.get("/api/v1/installers/me/leads", headers=headers)).json()
    quote = downgraded["items"][0]["quote"]
    assert (quote["postcode"], quote["email"], quote["phone"]) == ("M1", None, None)
    assert quote["first_name"] == "Sam"


async def test_installers_only_see_and_change_their_own_leads(
    client: httpx.AsyncClient, db: AsyncSession
):
    owner = await create_installer(db, "Owner Electrical")
    other = await create_installer(db, "Other Electrical")
    lead_id = await _lead_for(client, db, owner)

    foreign = await client.patch(
        f"/api/v1/installers/me/leads/{lead_id}",
        headers=auth_headers(other.user),
        json={"status": "won"},
    )
    assert foreign.status_code == 404

    back_to_sent = await client.patch(
        f"/api/v1/installers/me/leads/{lead_id}",
        headers=auth_headers(owner.user),
        json={"status": "sent"},
    )
    assert back_to_sent.status_code == 422


async def test_winning_a_lead_invites_one_verified_review(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_installer(db, "Winner Electrical")
    headers = auth_headers(installer.user)
    lead_id = await _lead_for(client, db, installer)
    lead_url = f"/api/v1/installers/me/leads/{lead_id}"

    viewed = await client.patch(lead_url, headers=headers, json={"status": "viewed"})
    assert viewed.json()["status"] == "viewed"
    assert fakes.emails.of("review_invitation") == []

    won = await client.patch(lead_url, headers=headers, json={"status": "won"})
    assert won.status_code == 200
    await client.patch(lead_url, headers=headers, json={"status": "won"})
    invitations = fakes.emails.of("review_invitation")
    assert len(invitations) == 1
    assert invitations[0].to == "sam@example.com"
    token = fakes.emails.token_from("review_invitation")

    invite = await client.get("/api/v1/reviews/invite", params={"token": token})
    assert invite.json() == {
        "installer_name": "Winner Electrical",
        "installer_slug": "winner-electrical",
    }

    created = await client.post("/api/v1/reviews", json={"token": token, **REVIEW})
    assert created.status_code == 201, created.text
    review = await db.scalar(select(Review))
    assert (review.status, str(review.quote_match_id)) == (ReviewStatus.PENDING, lead_id)

    # Pending reviews are invisible, and the invitation cannot be used twice.
    listing = await client.get("/api/v1/installers/winner-electrical/reviews")
    assert listing.json()["total"] == 0
    again = await client.post("/api/v1/reviews", json={"token": token, **REVIEW})
    assert (again.status_code, again.json()["error"]["code"]) == (400, "invalid_token")
    used = await client.get("/api/v1/reviews/invite", params={"token": token})
    assert (used.status_code, used.json()["error"]["code"]) == (404, "invalid_token")


async def test_review_tokens_cannot_be_forged_or_repurposed(
    client: httpx.AsyncClient, db: AsyncSession
):
    installer = await create_installer(db, "Target Electrical")
    lead_id = await _lead_for(client, db, installer)
    lead = await db.get(QuoteMatch, lead_id)

    # A correctly signed token for a lead that was never marked as won.
    uninvited = security.create_review_invite_token(lead.id)
    # An access token is signed with the same key but is the wrong type.
    access_token, _ = security.create_access_token(installer.user.id, Role.INSTALLER)

    for token in (uninvited, access_token, "not-a-token"):
        response = await client.post("/api/v1/reviews", json={"token": token, **REVIEW})
        assert response.status_code == 400, token
        assert (
            await client.get("/api/v1/reviews/invite", params={"token": token})
        ).status_code == 404

    invalid = await client.post(
        "/api/v1/reviews", json={"token": uninvited, **REVIEW, "rating": 6, "body": "Too short"}
    )
    assert set(invalid.json()["error"]["fields"]) == {"rating", "body"}


async def test_moderation_publishes_reviews_and_keeps_ratings_in_step(
    client: httpx.AsyncClient, db: AsyncSession
):
    installer = await create_installer(db, "Rated Electrical")
    admin = auth_headers(await create_user(db, role=Role.ADMIN))
    first = await create_review(db, installer, rating=5, status=ReviewStatus.PENDING)
    second = await create_review(db, installer, rating=4, status=ReviewStatus.PENDING)

    pending = await client.get("/api/v1/admin/reviews", headers=admin, params={"status": "pending"})
    assert pending.json()["total"] == 2

    for review in (first, second):
        published = await client.patch(
            f"/api/v1/admin/reviews/{review.id}", headers=admin, json={"status": "published"}
        )
        assert published.status_code == 200
        assert published.json()["published_at"] is not None

    profile = (await client.get("/api/v1/installers/rated-electrical")).json()
    assert (profile["rating_avg"], profile["review_count"]) == (4.5, 2)
    reviews = (await client.get("/api/v1/installers/rated-electrical/reviews")).json()
    assert reviews["total"] == 2
    assert reviews["items"][0].keys() == {
        "id",
        "rating",
        "title",
        "body",
        "author_name",
        "author_location",
        "verified",
        "created_at",
    }

    await client.patch(
        f"/api/v1/admin/reviews/{second.id}", headers=admin, json={"status": "rejected"}
    )
    profile = (await client.get("/api/v1/installers/rated-electrical")).json()
    assert (profile["rating_avg"], profile["review_count"]) == (5.0, 1)


async def test_featured_reviews_are_recent_published_and_well_rated(
    client: httpx.AsyncClient, db: AsyncSession
):
    live = await create_installer(db, "Live Electrical")
    suspended = await create_installer(db, "Suspended Electrical", status=InstallerStatus.SUSPENDED)
    await create_review(db, live, rating=5, title="Brilliant")
    await create_review(db, live, rating=4, title="Very good")
    await create_review(db, live, rating=3, title="Average")
    await create_review(db, live, rating=5, title="Not yet checked", status=ReviewStatus.PENDING)
    await create_review(db, suspended, rating=5, title="From a suspended installer")

    featured = (await client.get("/api/v1/reviews/featured")).json()
    assert [review["title"] for review in featured] == ["Very good", "Brilliant"]
    assert (await client.get("/api/v1/reviews/featured", params={"limit": 21})).status_code == 422


async def test_admin_approves_rejects_and_features_installers(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_installer(db, "New Applicant", status=InstallerStatus.PENDING)
    admin = auth_headers(await create_user(db, role=Role.ADMIN))
    url = f"/api/v1/admin/installers/{installer.id}"

    queue = await client.get(
        "/api/v1/admin/installers", headers=admin, params={"status": "pending"}
    )
    assert [item["slug"] for item in queue.json()["items"]] == ["new-applicant"]
    assert queue.json()["items"][0]["email"] == "new-applicant@example.com"

    approved = await client.patch(
        url, headers=admin, json={"status": "approved", "is_featured": True}
    )
    assert approved.status_code == 200
    body = approved.json()
    assert (body["status"], body["is_featured"]) == ("approved", True)
    assert body["approved_at"] is not None
    assert [email.to for email in fakes.emails.of("installer_approved")] == [
        "new-applicant@example.com"
    ]
    assert (await client.get("/api/v1/installers/new-applicant")).status_code == 200

    # Approving again changes nothing and sends no second email.
    await client.patch(url, headers=admin, json={"status": "approved"})
    assert len(fakes.emails.of("installer_approved")) == 1

    unverified = await client.patch(
        f"{url}/accreditations/ozev", headers=admin, json={"verified": False}
    )
    assert unverified.json()["accreditations"][0]["verified"] is False
    not_listed = await client.patch(
        f"{url}/accreditations/mcs", headers=admin, json={"verified": True}
    )
    assert not_listed.status_code == 404

    rejected = await client.patch(url, headers=admin, json={"status": "rejected"})
    assert rejected.json()["status"] == "rejected"
    assert len(fakes.emails.of("installer_rejected")) == 1
    assert (await client.get("/api/v1/installers/new-applicant")).status_code == 404


async def test_back_office_lists_quotes_and_contact_messages(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    admin = auth_headers(await create_user(db, role=Role.ADMIN))
    await client.post("/api/v1/quotes", json=quote_payload())
    sent = await client.post(
        "/api/v1/contact",
        json={
            "name": "Jo Bloggs",
            "email": "jo@example.com",
            "subject": "getting_quotes",
            "message": "How long do quotes usually take to arrive?",
        },
    )
    assert sent.status_code == 202
    assert [email.template for email in fakes.emails.sent[-2:]] == [
        "contact_received",
        "contact_ack",
    ]
    received = fakes.emails.of("contact_received")[0]
    assert received.reply_to == "jo@example.com"

    quotes = (await client.get("/api/v1/admin/quotes", headers=admin)).json()
    assert (quotes["total"], quotes["items"][0]["email"]) == (1, "sam@example.com")
    messages = (await client.get("/api/v1/admin/contact-messages", headers=admin)).json()
    assert (messages["total"], messages["items"][0]["subject"]) == (1, "getting_quotes")

    bot = await client.post(
        "/api/v1/contact",
        json={
            "name": "Bot",
            "email": "bot@example.com",
            "subject": "other",
            "message": "Buy cheap watches today, limited offer.",
            "website": "https://spam.example",
        },
    )
    assert bot.status_code == 202
    messages = (await client.get("/api/v1/admin/contact-messages", headers=admin)).json()
    assert messages["total"] == 1


async def test_admin_endpoints_reject_everyone_else(client: httpx.AsyncClient, db: AsyncSession):
    installer = await create_installer(db, "Curious Installer")
    paths = [
        ("GET", "/api/v1/admin/installers"),
        ("GET", "/api/v1/admin/reviews"),
        ("GET", "/api/v1/admin/quotes"),
        ("GET", "/api/v1/admin/contact-messages"),
        ("PATCH", f"/api/v1/admin/installers/{installer.id}"),
    ]
    for method, path in paths:
        anonymous = await client.request(method, path, json={})
        assert anonymous.status_code == 401, path
        forbidden = await client.request(
            method, path, json={}, headers=auth_headers(installer.user)
        )
        assert forbidden.status_code == 403, path
    # ...and an admin has no installer profile, so installer-only routes refuse them.
    admin = auth_headers(await create_user(db, role=Role.ADMIN))
    assert (await client.get("/api/v1/installers/me", headers=admin)).status_code == 403
