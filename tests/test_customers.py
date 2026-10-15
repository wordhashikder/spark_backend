"""Customer accounts: magic links, sessions and the quote dashboard."""

from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, CustomerLoginLink, QuoteMatch
from app.models.base import utcnow
from tests.helpers import Fakes, auth_headers, create_installer, quote_payload

OFFER = {
    "amount": "949.00",
    "includes_vat": True,
    "description": "Supply and fit a 7kW tethered charger, testing and certificate.",
}


def _link_token(fakes: Fakes, template: str = "quote_confirmation") -> str:
    link = fakes.emails.of(template)[-1].context["link"]
    assert urlparse(link).path == "/uk/my-quotes/verify/"
    return parse_qs(urlparse(link).query)["token"][0]


async def _sign_in(client: httpx.AsyncClient, fakes: Fakes) -> dict[str, str]:
    verified = await client.post("/api/v1/customer/auth/verify", json={"token": _link_token(fakes)})
    assert verified.status_code == 200, verified.text
    return {"Authorization": f"Bearer {verified.json()['session_token']}"}


async def test_every_quote_request_emails_a_magic_link_and_creates_the_customer(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    await client.post("/api/v1/quotes", json=quote_payload())
    await client.post("/api/v1/quotes", json=quote_payload(first_name="Samantha"))

    customers = list(await db.scalars(select(Customer)))
    assert [c.email for c in customers] == ["sam@example.com"]  # one record per address
    assert customers[0].first_name == "Samantha"
    emails = fakes.emails.of("quote_confirmation")
    assert len(emails) == 2
    assert all(email.context["link"] for email in emails)
    # Only a hash of the token is stored.
    stored = await db.scalars(select(CustomerLoginLink.token_hash))
    assert _link_token(fakes) not in list(stored)


async def test_magic_link_signs_in_and_the_session_survives(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    installer = await create_installer(db, "Pro Manchester")
    await client.post("/api/v1/quotes", json=quote_payload())
    headers = await _sign_in(client, fakes)

    me = await client.get("/api/v1/customer/me", headers=headers)
    assert me.json()["email"] == "sam@example.com"
    overview = await client.get("/api/v1/customer/overview", headers=headers)
    request = overview.json()["requests"][0]
    assert request["status"] == "matching"
    assert request["installers_matched"] == 1
    assert request["quotes_received"] == 0

    detail = await client.get(f"/api/v1/customer/requests/{request['id']}", headers=headers)
    body = detail.json()
    assert body["installers"][0]["installer"]["business_name"] == installer.business_name
    assert body["installers"][0]["state"] == "awaiting_quote"
    assert [step["state"] for step in body["journey"]] == [
        "done",
        "done",
        "current",
        "upcoming",
        "upcoming",
    ]

    # The same link works again right after first use (email scanners), then stops.
    again = await client.post("/api/v1/customer/auth/verify", json={"token": _link_token(fakes)})
    assert again.status_code == 200
    link = await db.scalar(select(CustomerLoginLink))
    link.used_at = utcnow() - timedelta(minutes=30)
    await db.commit()
    late = await client.post("/api/v1/customer/auth/verify", json={"token": _link_token(fakes)})
    assert late.status_code == 400
    # ... but the session already started keeps working.
    assert (await client.get("/api/v1/customer/me", headers=headers)).status_code == 200


async def test_expired_and_unknown_links_are_refused(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    await client.post("/api/v1/quotes", json=quote_payload())
    link = await db.scalar(select(CustomerLoginLink))
    link.expires_at = utcnow() - timedelta(minutes=1)
    await db.commit()
    expired = await client.post("/api/v1/customer/auth/verify", json={"token": _link_token(fakes)})
    garbage = await client.post("/api/v1/customer/auth/verify", json={"token": "x" * 40})
    assert expired.status_code == garbage.status_code == 400
    assert expired.json()["error"]["code"] == garbage.json()["error"]["code"]
    assert (await client.get("/api/v1/customer/me")).status_code == 401


async def test_request_new_link_does_not_reveal_whether_the_address_is_known(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    await client.post("/api/v1/quotes", json=quote_payload())
    known = await client.post(
        "/api/v1/customer/auth/request-link", json={"email": "sam@example.com"}
    )
    unknown = await client.post(
        "/api/v1/customer/auth/request-link", json={"email": "who@example.com"}
    )
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert [e.to for e in fakes.emails.of("magic_link")] == ["sam@example.com"]


async def test_logout_ends_the_session(client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes):
    await client.post("/api/v1/quotes", json=quote_payload())
    headers = await _sign_in(client, fakes)
    assert (await client.post("/api/v1/customer/auth/logout", headers=headers)).status_code == 204
    assert (await client.get("/api/v1/customer/me", headers=headers)).status_code == 401


async def test_customer_compares_quotes_replies_and_accepts(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    installer = await create_installer(db, "Pro Manchester")
    await client.post("/api/v1/quotes", json=quote_payload())
    lead = await db.scalar(select(QuoteMatch).where(QuoteMatch.installer_id == installer.id))
    installer_headers = auth_headers(installer.user)
    started = await client.post(
        "/api/v1/installers/me/conversations",
        json={"lead_id": str(lead.id)},
        headers=installer_headers,
    )
    conversation_id = started.json()["id"]
    sent = await client.post(
        f"/api/v1/installers/me/conversations/{conversation_id}/quotes",
        json=OFFER,
        headers=installer_headers,
    )
    offer_id = sent.json()["id"]

    headers = await _sign_in(client, fakes)
    overview = (await client.get("/api/v1/customer/overview", headers=headers)).json()
    assert overview["requests"][0]["quotes_received"] == 1
    assert overview["requests"][0]["average_price"] == "949.00"
    assert overview["unread_messages"] == 1
    detail = (
        await client.get(
            f"/api/v1/customer/requests/{overview['requests'][0]['id']}", headers=headers
        )
    ).json()
    assert detail["quotes"][0]["amount"] == "949.00"
    assert detail["quotes"][0]["installer"]["slug"] == installer.slug

    thread = await client.get(f"/api/v1/customer/conversations/{conversation_id}", headers=headers)
    assert thread.json()["homeowner_email"] is None
    reply = await client.post(
        f"/api/v1/customer/conversations/{conversation_id}/messages",
        json={"body": "Can you start on Thursday?"},
        headers=headers,
    )
    assert reply.status_code == 201
    assert fakes.emails.of("conversation_reply")[-1].to == "pro-manchester@example.com"
    accepted = await client.post(
        f"/api/v1/customer/quotes/{offer_id}/respond",
        json={"decision": "accept"},
        headers=headers,
    )
    assert accepted.json()["status"] == "accepted"
    overview = (await client.get("/api/v1/customer/overview", headers=headers)).json()
    assert overview["requests"][0]["status"] == "accepted"
    assert overview["unread_messages"] == 0


async def test_customers_cannot_see_each_others_data(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    installer = await create_installer(db, "Pro Manchester")
    await client.post("/api/v1/quotes", json=quote_payload())
    lead = await db.scalar(select(QuoteMatch).where(QuoteMatch.installer_id == installer.id))
    started = await client.post(
        "/api/v1/installers/me/conversations",
        json={"lead_id": str(lead.id)},
        headers=auth_headers(installer.user),
    )
    await client.post("/api/v1/quotes", json=quote_payload(email="other@example.com"))
    other = await client.post("/api/v1/customer/auth/verify", json={"token": _link_token(fakes)})
    headers = {"Authorization": f"Bearer {other.json()['session_token']}"}
    assert (
        await client.get(f"/api/v1/customer/conversations/{started.json()['id']}", headers=headers)
    ).status_code == 404
    overview = (await client.get("/api/v1/customer/overview", headers=headers)).json()
    assert len(overview["requests"]) == 1


async def test_profile_update_and_erase(client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes):
    await client.post("/api/v1/quotes", json=quote_payload())
    headers = await _sign_in(client, fakes)
    updated = await client.patch(
        "/api/v1/customer/me", json={"first_name": "Sammy", "phone": ""}, headers=headers
    )
    assert updated.json()["first_name"] == "Sammy"
    assert (await client.delete("/api/v1/customer/me", headers=headers)).status_code == 204
    assert (await client.get("/api/v1/customer/me", headers=headers)).status_code == 401


async def test_admin_sees_customers_and_can_resend_a_link(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    from app.core.enums import Role
    from tests.helpers import create_user

    admin = await create_user(db, role=Role.ADMIN)
    headers = auth_headers(admin)
    await client.post("/api/v1/quotes", json=quote_payload())
    listing = await client.get("/api/v1/admin/customers", headers=headers)
    row = listing.json()["items"][0]
    assert (row["email"], row["requests"]) == ("sam@example.com", 1)
    assert (
        await client.get("/api/v1/admin/customers", params={"q": "nobody"}, headers=headers)
    ).json()["total"] == 0
    sent = await client.post(f"/api/v1/admin/customers/{row['id']}/magic-link", headers=headers)
    assert sent.status_code == 202
    assert fakes.emails.of("magic_link")[-1].to == "sam@example.com"
    erased = await client.delete(f"/api/v1/admin/customers/{row['id']}", headers=headers)
    assert erased.status_code == 204
