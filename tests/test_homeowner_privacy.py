"""Installers only ever see a homeowner's first name; the team and the homeowner see it all."""

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.enums import Role
from app.core.names import given_name, hide_surname
from app.models import InstallerEnquiry, QuoteMatch, QuoteRequest
from tests.helpers import Fakes, auth_headers, create_installer, create_user, quote_payload

SURNAME = "Taylor"
OFFER = {
    "amount": "949.00",
    "includes_vat": True,
    "description": "Supply and fit a 7kW tethered charger, 10m cable run, testing and certificate.",
}


@pytest.mark.parametrize(
    ("typed", "shown"),
    [
        ("Sam Taylor", "Sam"),
        ("  Sam   Taylor  ", "Sam"),
        ("Sam", "Sam"),
        ("Mary-Jane O'Neil", "Mary-Jane"),
        ("Mr Sam Taylor", "Sam"),
        ("Dr. Sam Taylor", "Sam"),
        ("Mrs", "Mrs"),
        ("Sam Taylor-Jones", "Sam"),
        ("", ""),
    ],
)
def test_given_name(typed: str, shown: str):
    assert given_name(typed) == shown


def test_hide_surname_only_changes_the_full_name():
    assert (
        hide_surname("Sam Taylor accepted quote QT-1.", "Sam Taylor") == "Sam accepted quote QT-1."
    )
    assert hide_surname("Sam accepted quote QT-1.", "Sam") == "Sam accepted quote QT-1."


async def _journey(client: httpx.AsyncClient, db: AsyncSession):
    """A homeowner who typed a full name gets a quote, messages and accepts an offer."""
    installer = await create_installer(db, "Pro Manchester")
    await client.post("/api/v1/quotes", json=quote_payload(first_name="Sam Taylor"))
    lead = await db.scalar(select(QuoteMatch).where(QuoteMatch.installer_id == installer.id))
    headers = auth_headers(installer.user)
    conversation = (
        await client.post(
            "/api/v1/installers/me/conversations", json={"lead_id": str(lead.id)}, headers=headers
        )
    ).json()
    base = f"/api/v1/installers/me/conversations/{conversation['id']}"
    await client.post(f"{base}/messages", json={"body": "Hello, when suits?"}, headers=headers)
    offer = (await client.post(f"{base}/quotes", json=OFFER, headers=headers)).json()
    token = security.create_conversation_token(uuid.UUID(conversation["id"]))
    await client.post(
        "/api/v1/conversation-links/messages", json={"token": token, "body": "Thursday works."}
    )
    await client.post(
        f"/api/v1/conversation-links/quotes/{offer['id']}",
        json={"token": token, "decision": "accept", "note": "Let's go ahead."},
    )
    return installer, lead, headers, conversation, base, token


async def test_installers_never_see_a_homeowners_surname_in_the_dashboard(
    client: httpx.AsyncClient, db: AsyncSession
):
    _, lead, headers, _conversation, base, _ = await _journey(client, db)
    responses = [
        await client.get("/api/v1/installers/me/leads", headers=headers),
        await client.get(f"/api/v1/installers/me/leads/{lead.id}", headers=headers),
        await client.get("/api/v1/installers/me/conversations", headers=headers),
        await client.get(base, headers=headers),
        await client.get("/api/v1/installers/me/quotes", headers=headers),
        await client.get("/api/v1/installers/me/summary", headers=headers),
    ]
    for response in responses:
        assert response.status_code == 200
        assert SURNAME not in response.text, response.url
    assert responses[1].json()["quote"]["first_name"] == "Sam"
    assert responses[3].json()["homeowner_name"] == "Sam"
    assert responses[4].json()["items"][0]["homeowner_name"] == "Sam"
    # The line the system wrote when the homeowner accepted names them by first name.
    system = [m["body"] for m in responses[3].json()["messages"] if m["sender"] == "system"]
    assert len(system) == 1
    assert system[0].startswith("Sam accepted quote QT-")
    assert responses[2].json()["items"][0]["last_message"].startswith("Sam accepted quote QT-")


async def test_installers_never_see_a_homeowners_surname_in_emails(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    installer, *_ = await _journey(client, db)
    to_installer = [e for e in fakes.emails.sent if e.to == installer.user.email]
    assert {e.template for e in to_installer} >= {
        "new_lead",
        "conversation_reply",
        "offer_response",
    }
    for email in to_installer:
        assert SURNAME not in email.subject, email.template
        rendered = fakes.emails._renderer.render(email)
        assert SURNAME not in str(rendered), email.template
    assert fakes.emails.of("new_lead")[0].context["first_name"] == "Sam"


async def test_the_team_and_the_homeowner_still_see_the_full_name(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    _, _, _, conversation, _, token = await _journey(client, db)
    admin = auth_headers(await create_user(db, role=Role.ADMIN))
    detail = (
        await client.get(f"/api/v1/admin/conversations/{conversation['id']}", headers=admin)
    ).json()
    assert detail["homeowner_name"] == "Sam Taylor"
    assert any("Sam Taylor accepted quote" in m["body"] for m in detail["messages"])
    listed = (await client.get("/api/v1/admin/conversations", headers=admin)).json()
    assert listed["items"][0]["homeowner_name"] == "Sam Taylor"

    quote = await db.scalar(select(QuoteRequest))
    request = (await client.get(f"/api/v1/admin/quotes/{quote.id}", headers=admin)).json()
    assert request["first_name"] == "Sam Taylor"

    own = (await client.post("/api/v1/conversation-links/view", json={"token": token})).json()
    assert own["homeowner_name"] == "Sam Taylor"
    # Their own confirmation email greets them as they typed their name.
    assert fakes.emails.of("quote_confirmation")[0].context["first_name"] == "Sam Taylor"


async def test_a_team_message_names_the_homeowner_by_first_name_to_the_installer_only(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    installer, _, _, conversation, _, _ = await _journey(client, db)
    admin = auth_headers(await create_user(db, role=Role.ADMIN))
    await client.post(
        f"/api/v1/admin/conversations/{conversation['id']}/messages",
        json={"body": "Please reply when you can."},
        headers=admin,
    )
    sent = fakes.emails.of("conversation_team_message")
    to_installer = next(e for e in sent if e.to == installer.user.email)
    to_homeowner = next(e for e in sent if e.to == "sam@example.com")
    assert SURNAME not in to_installer.subject
    assert SURNAME not in str(fakes.emails._renderer.render(to_installer))
    assert to_homeowner.context["name"] == "Sam Taylor"


async def test_enquiries_show_installers_the_first_name_only(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    installer = await create_installer(db, "Pro Manchester")
    await client.post(
        f"/api/v1/installers/{installer.slug}/enquiries",
        json={
            "name": "Sam Taylor",
            "email": "sam@example.com",
            "phone": "07700 900123",
            "message": "Could you quote for a tethered charger on the front of the house?",
        },
    )
    headers = auth_headers(installer.user)
    listed = await client.get("/api/v1/installers/me/enquiries", headers=headers)
    assert listed.json()["items"][0]["name"] == "Sam"
    assert SURNAME not in listed.text

    notification = fakes.emails.of("installer_enquiry")[0]
    assert SURNAME not in notification.subject
    assert SURNAME not in str(fakes.emails._renderer.render(notification))

    enquiry = await db.scalar(select(InstallerEnquiry))
    started = await client.post(
        "/api/v1/installers/me/conversations",
        json={"enquiry_id": str(enquiry.id)},
        headers=headers,
    )
    assert started.status_code == 200, started.text
    assert started.json()["homeowner_name"] == "Sam"
    assert SURNAME not in started.text

    # The team still sees who wrote in, in full.
    admin = auth_headers(await create_user(db, role=Role.ADMIN))
    everything = (await client.get("/api/v1/admin/enquiries", headers=admin)).json()
    assert everything["items"][0]["name"] == "Sam Taylor"
