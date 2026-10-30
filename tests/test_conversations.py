"""In-app quotes and messages between installers and homeowners."""

import uuid
from datetime import timedelta
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.enums import LeadStatus, Role
from app.models import Customer, CustomerLoginLink, QuoteMatch
from tests.helpers import Fakes, Plan, auth_headers, create_installer, create_user, quote_payload

OFFER = {
    "amount": "949.00",
    "includes_vat": True,
    "description": "Supply and fit a 7kW tethered charger, 10m cable run, testing and certificate.",
    "message": "Happy to answer any questions.",
}


async def _lead(client: httpx.AsyncClient, db: AsyncSession, plan: Plan = Plan.PRO):
    installer = await create_installer(db, "Pro Manchester", plan=plan)
    await client.post("/api/v1/quotes", json=quote_payload())
    lead = await db.scalar(select(QuoteMatch).where(QuoteMatch.installer_id == installer.id))
    return installer, lead


def _private_token(conversation_id: str) -> str:
    """The token behind the homeowner's private conversation page (a fallback link)."""
    return security.create_conversation_token(uuid.UUID(conversation_id))


async def test_installer_messages_and_quotes_and_the_homeowner_replies(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    installer, lead = await _lead(client, db)
    headers = auth_headers(installer.user)

    started = await client.post(
        "/api/v1/installers/me/conversations", json={"lead_id": str(lead.id)}, headers=headers
    )
    assert started.status_code == 200, started.text
    conversation = started.json()
    assert conversation["homeowner_email"] == "sam@example.com"
    assert conversation["job"]["kind"] == "lead"
    # Opening it again returns the same conversation.
    again = await client.post(
        "/api/v1/installers/me/conversations", json={"lead_id": str(lead.id)}, headers=headers
    )
    assert again.json()["id"] == conversation["id"]

    base = f"/api/v1/installers/me/conversations/{conversation['id']}"
    message = await client.post(
        f"{base}/messages", json={"body": "Hi Sam, when suits for a survey?"}, headers=headers
    )
    assert message.status_code == 201
    email = fakes.emails.of("conversation_message")[-1]
    assert (email.to, email.reply_to) == ("sam@example.com", "pro-manchester@example.com")
    token = _private_token(conversation["id"])

    offer = await client.post(f"{base}/quotes", json=OFFER, headers=headers)
    assert offer.status_code == 201, offer.text
    assert offer.json()["reference"].startswith("QT-")
    assert fakes.emails.of("conversation_offer")[-1].context["amount"] == "£949.00"

    await db.refresh(lead)
    assert lead.status is LeadStatus.CONTACTED

    # The homeowner opens the private link: no email or phone of their own is echoed back.
    view = await client.post("/api/v1/conversation-links/view", json={"token": token})
    assert view.status_code == 200
    thread = view.json()
    assert thread["homeowner_email"] is None
    assert [m["sender"] for m in thread["messages"]] == ["installer", "installer"]
    assert len(thread["offers"]) == 1

    reply = await client.post(
        "/api/v1/conversation-links/messages",
        json={"token": token, "body": "Thursday morning works."},
    )
    assert reply.status_code == 201
    assert fakes.emails.of("conversation_reply")[-1].to == "pro-manchester@example.com"

    unread = await client.get(
        "/api/v1/installers/me/conversations", params={"unread": "true"}, headers=headers
    )
    assert unread.json()["total"] == 1
    assert unread.json()["items"][0]["last_message"] == "Thursday morning works."

    accepted = await client.post(
        f"/api/v1/conversation-links/quotes/{offer.json()['id']}",
        json={"token": token, "decision": "accept", "note": "Let's go ahead."},
    )
    assert accepted.json()["status"] == "accepted"
    assert fakes.emails.of("offer_response")[-1].context["accepted"] is True

    answered_twice = await client.post(
        f"/api/v1/conversation-links/quotes/{offer.json()['id']}",
        json={"token": token, "decision": "decline"},
    )
    assert answered_twice.json()["error"]["code"] == "quote_not_open"

    summary = await client.get("/api/v1/installers/me/summary", headers=headers)
    assert summary.json()["accepted_quotes"] == 1

    # Opening the thread marks it read.
    await client.get(base, headers=headers)
    unread = await client.get(
        "/api/v1/installers/me/conversations", params={"unread": "true"}, headers=headers
    )
    assert unread.json()["total"] == 0

    quotes = await client.get("/api/v1/installers/me/quotes", headers=headers)
    assert quotes.json()["items"][0]["homeowner_name"] == "Sam"


async def test_quote_can_be_withdrawn_while_open(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    installer, lead = await _lead(client, db)
    headers = auth_headers(installer.user)
    conversation = (
        await client.post(
            "/api/v1/installers/me/conversations", json={"lead_id": str(lead.id)}, headers=headers
        )
    ).json()
    offer = (
        await client.post(
            f"/api/v1/installers/me/conversations/{conversation['id']}/quotes",
            json=OFFER,
            headers=headers,
        )
    ).json()
    withdrawn = await client.post(
        f"/api/v1/installers/me/quotes/{offer['id']}/withdraw", headers=headers
    )
    assert withdrawn.json()["status"] == "withdrawn"
    token = _private_token(conversation["id"])
    response = await client.post(
        f"/api/v1/conversation-links/quotes/{offer['id']}",
        json={"token": token, "decision": "accept"},
    )
    assert response.json()["error"]["code"] == "quote_not_open"


async def test_installers_only_see_their_own_conversations(
    client: httpx.AsyncClient, db: AsyncSession
):
    installer, lead = await _lead(client, db)
    other = await create_installer(db, "Other Installer")
    conversation = (
        await client.post(
            "/api/v1/installers/me/conversations",
            json={"lead_id": str(lead.id)},
            headers=auth_headers(installer.user),
        )
    ).json()
    response = await client.get(
        f"/api/v1/installers/me/conversations/{conversation['id']}",
        headers=auth_headers(other.user),
    )
    assert response.status_code == 404
    stolen = await client.post(
        "/api/v1/installers/me/conversations",
        json={"lead_id": str(lead.id)},
        headers=auth_headers(other.user),
    )
    assert stolen.status_code == 404


async def test_free_plan_cannot_message_or_quote(client: httpx.AsyncClient, db: AsyncSession):
    installer, lead = await _lead(client, db)
    installer.plan = Plan.FREE
    await db.commit()
    response = await client.post(
        "/api/v1/installers/me/conversations",
        json={"lead_id": str(lead.id)},
        headers=auth_headers(installer.user),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "plan_required"


async def test_validation_and_bad_links(client: httpx.AsyncClient, db: AsyncSession):
    installer, lead = await _lead(client, db)
    headers = auth_headers(installer.user)
    both = await client.post(
        "/api/v1/installers/me/conversations",
        json={"lead_id": str(lead.id), "enquiry_id": str(lead.id)},
        headers=headers,
    )
    assert both.status_code == 422
    conversation = (
        await client.post(
            "/api/v1/installers/me/conversations", json={"lead_id": str(lead.id)}, headers=headers
        )
    ).json()
    bad_offer = await client.post(
        f"/api/v1/installers/me/conversations/{conversation['id']}/quotes",
        json=OFFER | {"amount": "0"},
        headers=headers,
    )
    assert bad_offer.status_code == 422
    view = await client.post("/api/v1/conversation-links/view", json={"token": "nope"})
    assert view.json()["error"]["code"] == "invalid_token"


async def test_admin_reads_every_conversation(client: httpx.AsyncClient, db: AsyncSession):
    installer, lead = await _lead(client, db)
    conversation = (
        await client.post(
            "/api/v1/installers/me/conversations",
            json={"lead_id": str(lead.id)},
            headers=auth_headers(installer.user),
        )
    ).json()
    admin = await create_user(db, role=Role.ADMIN)
    listed = await client.get("/api/v1/admin/conversations", headers=auth_headers(admin))
    assert [item["id"] for item in listed.json()["items"]] == [conversation["id"]]
    detail = await client.get(
        f"/api/v1/admin/conversations/{conversation['id']}", headers=auth_headers(admin)
    )
    assert detail.json()["homeowner_email"] == "sam@example.com"
    forbidden = await client.get(
        "/api/v1/admin/conversations", headers=auth_headers(installer.user)
    )
    assert forbidden.status_code == 403


async def test_homeowner_emails_open_the_conversation_in_their_quote_dashboard(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    installer, lead = await _lead(client, db)
    headers = auth_headers(installer.user)
    conversation = (
        await client.post(
            "/api/v1/installers/me/conversations", json={"lead_id": str(lead.id)}, headers=headers
        )
    ).json()
    base = f"/api/v1/installers/me/conversations/{conversation['id']}"
    await client.post(f"{base}/messages", json={"body": "Hi Sam"}, headers=headers)
    await client.post(f"{base}/quotes", json=OFFER, headers=headers)

    for template in ("conversation_message", "conversation_offer"):
        link = urlparse(fakes.emails.of(template)[-1].context["link"])
        query = parse_qs(link.query)
        # The button signs the homeowner in and lands on this very conversation.
        assert link.path == "/uk/my-quotes/verify/"
        assert unquote(query["next"][0]) == f"/uk/my-quotes/messages/?c={conversation['id']}"
        verified = await client.post(
            "/api/v1/customer/auth/verify", json={"token": query["token"][0]}
        )
        assert verified.status_code == 200, verified.text
        session = {"Authorization": f"Bearer {verified.json()['session_token']}"}
        thread = await client.get(
            f"/api/v1/customer/conversations/{conversation['id']}", headers=session
        )
        assert thread.status_code == 200
        assert [offer["status"] for offer in thread.json()["offers"]] == ["sent"]

    # A link from an email stays valid for days (not just minutes).
    stored = await db.scalars(select(CustomerLoginLink))
    long_lived = [
        link for link in stored if link.expires_at - link.created_at >= timedelta(days=29)
    ]
    assert len(long_lived) == 2  # one per email; the sign-up confirmation link stays short


async def test_homeowner_without_a_dashboard_gets_the_private_conversation_page(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    installer, lead = await _lead(client, db)
    headers = auth_headers(installer.user)
    conversation = (
        await client.post(
            "/api/v1/installers/me/conversations", json={"lead_id": str(lead.id)}, headers=headers
        )
    ).json()
    # The customer record was erased (GDPR): the email must still work.
    await db.execute(delete(Customer))
    await db.commit()
    await client.post(
        f"/api/v1/installers/me/conversations/{conversation['id']}/messages",
        json={"body": "Hi Sam"},
        headers=headers,
    )
    link = urlparse(fakes.emails.of("conversation_message")[-1].context["link"])
    assert link.path == "/messages/"
    view = await client.post(
        "/api/v1/conversation-links/view", json={"token": parse_qs(link.query)["token"][0]}
    )
    assert view.status_code == 200
