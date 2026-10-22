"""Every eligible installer is told about a request; only the first few may quote it."""

import asyncio
from urllib.parse import parse_qs, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import LeadStatus
from app.models import Installer, QuoteMatch
from tests.helpers import Fakes, Plan, auth_headers, create_installer, quote_payload

BASE = "/api/v1/installers/me"
OFFER = {
    "amount": "949.00",
    "includes_vat": True,
    "description": "Supply and fit a 7kW tethered charger, 10m cable run, testing and certificate.",
}


async def _lead_of(db: AsyncSession, installer: Installer) -> QuoteMatch:
    lead = await db.scalar(select(QuoteMatch).where(QuoteMatch.installer_id == installer.id))
    assert lead is not None
    return lead


async def _start(client: httpx.AsyncClient, installer: Installer, lead: QuoteMatch):
    return await client.post(
        f"{BASE}/conversations",
        json={"lead_id": str(lead.id)},
        headers=auth_headers(installer.user),
    )


async def _installers(db: AsyncSession, count: int) -> list[Installer]:
    return [await create_installer(db, f"Installer {index}") for index in range(count)]


async def test_free_installer_sees_only_the_headline_and_is_asked_to_upgrade(
    client: httpx.AsyncClient, db: AsyncSession
):
    free = await create_installer(db, "Free Installer", plan=Plan.FREE)
    await client.post("/api/v1/quotes", json=quote_payload(notes="Side gate is narrow."))
    lead = await _lead_of(db, free)
    headers = auth_headers(free.user)

    listed = (await client.get(f"{BASE}/leads", headers=headers)).json()["items"][0]
    single = (await client.get(f"{BASE}/leads/{lead.id}", headers=headers)).json()
    assert listed["id"] == single["id"] == str(lead.id)
    assert single["access"] == "upgrade_required"
    quote = single["quote"]
    assert (quote["first_name"], quote["district"], quote["timing"]) == (
        "Sam",
        "Manchester",
        "within_month",
    )
    assert quote["installation_type"]
    # Nothing beyond the headline: no contact details, answers or notes, and a short postcode.
    for hidden in (
        "email",
        "phone",
        "notes",
        "charger_location",
        "existing_charger",
        "charger_followup",
        "fuse_box_distance",
        "vehicle",
    ):
        assert quote[hidden] is None, hidden
    assert quote["postcode"] == "M1"

    # Opening the enquiry to respond, or working the lead, asks them to upgrade.
    for response in (
        await _start(client, free, lead),
        await client.patch(
            f"{BASE}/leads/{lead.id}", json={"status": "contacted"}, headers=headers
        ),
    ):
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "plan_required"
    await db.refresh(lead)
    assert lead.status is LeadStatus.SENT
    assert lead.responded_at is None


async def test_paid_installer_opens_the_whole_enquiry(client: httpx.AsyncClient, db: AsyncSession):
    pro = await create_installer(db, "Pro Installer")
    await client.post("/api/v1/quotes", json=quote_payload(notes="Side gate is narrow."))
    lead = await _lead_of(db, pro)

    single = (await client.get(f"{BASE}/leads/{lead.id}", headers=auth_headers(pro.user))).json()
    assert single["access"] == "open"
    assert single["quote"]["email"] == "sam@example.com"
    assert single["quote"]["notes"] == "Side gate is narrow."
    assert single["quote"]["charger_location"]
    assert single["progress"]["slots_total"] == 5
    assert single["progress"]["responders"] == 0


async def test_lead_belongs_to_its_installer(client: httpx.AsyncClient, db: AsyncSession):
    first, second = await _installers(db, 2)
    await client.post("/api/v1/quotes", json=quote_payload())
    lead = await _lead_of(db, first)
    other = await client.get(f"{BASE}/leads/{lead.id}", headers=auth_headers(second.user))
    assert other.status_code == 404


async def test_only_the_first_five_installers_to_respond_can_quote(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    installers = await _installers(db, 7)
    await client.post("/api/v1/quotes", json=quote_payload())
    assert len(fakes.emails.of("new_lead")) == 7  # all seven were told

    conversations = []
    for installer in installers:
        lead = await _lead_of(db, installer)
        started = await _start(client, installer, lead)
        assert started.status_code == 200, started.text  # opening takes no place
        conversations.append(started.json()["id"])

    for installer, conversation in zip(installers[:5], conversations, strict=False):
        sent = await client.post(
            f"{BASE}/conversations/{conversation}/quotes",
            json=OFFER,
            headers=auth_headers(installer.user),
        )
        assert sent.status_code == 201, sent.text

    # The sixth installer is refused, whether they message or quote.
    sixth = installers[5]
    for path, body in (("messages", {"body": "Hello"}), ("quotes", OFFER)):
        refused = await client.post(
            f"{BASE}/conversations/{conversations[5]}/{path}",
            json=body,
            headers=auth_headers(sixth.user),
        )
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "enquiry_full"

    # ... and cannot even open it afresh; the dashboard shows the enquiry as full.
    sixth_lead = await _lead_of(db, sixth)
    seen = (
        await client.get(f"{BASE}/leads/{sixth_lead.id}", headers=auth_headers(sixth.user))
    ).json()
    assert seen["access"] == "full"
    # Latecomers get the headline only, and cannot work the lead either.
    assert seen["quote"]["email"] is None
    assert seen["quote"]["notes"] is None
    worked = await client.patch(
        f"{BASE}/leads/{sixth_lead.id}",
        json={"status": "won"},
        headers=auth_headers(sixth.user),
    )
    assert worked.status_code == 409
    assert worked.json()["error"]["code"] == "enquiry_full"
    assert (seen["progress"]["responders"], seen["progress"]["slots_total"]) == (5, 5)

    # The five keep their places: they can still follow up.
    follow_up = await client.post(
        f"{BASE}/conversations/{conversations[0]}/messages",
        json={"body": "Any questions?"},
        headers=auth_headers(installers[0].user),
    )
    assert follow_up.status_code == 201
    first_lead = (
        await client.get(
            f"{BASE}/leads/{(await _lead_of(db, installers[0])).id}",
            headers=auth_headers(installers[0].user),
        )
    ).json()
    assert first_lead["access"] == "open"


async def test_a_full_enquiry_refuses_new_installers_before_the_quote_form_opens(
    client: httpx.AsyncClient, db: AsyncSession
):
    installers = await _installers(db, 6)
    await client.post("/api/v1/quotes", json=quote_payload())
    for installer in installers[:5]:
        lead = await _lead_of(db, installer)
        conversation = (await _start(client, installer, lead)).json()["id"]
        await client.post(
            f"{BASE}/conversations/{conversation}/messages",
            json={"body": "Hi"},
            headers=auth_headers(installer.user),
        )
    late = await _start(client, installers[5], await _lead_of(db, installers[5]))
    assert late.status_code == 409
    assert late.json()["error"]["code"] == "enquiry_full"


async def test_simultaneous_replies_cannot_exceed_the_limit(
    client: httpx.AsyncClient, db: AsyncSession
):
    installers = await _installers(db, 8)
    await client.post("/api/v1/quotes", json=quote_payload())
    conversations = {}
    for installer in installers:
        lead = await _lead_of(db, installer)
        conversations[installer.id] = (await _start(client, installer, lead)).json()["id"]

    results = await asyncio.gather(
        *(
            client.post(
                f"{BASE}/conversations/{conversations[installer.id]}/quotes",
                json=OFFER,
                headers=auth_headers(installer.user),
            )
            for installer in installers
        )
    )
    codes = sorted(response.status_code for response in results)
    assert codes == [201] * 5 + [409] * 3


async def test_homeowner_only_meets_installers_who_responded(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    installers = await _installers(db, 3)
    await client.post("/api/v1/quotes", json=quote_payload())
    link = fakes.emails.of("quote_confirmation")[-1].context["link"]
    token = parse_qs(urlparse(link).query)["token"][0]
    verified = await client.post("/api/v1/customer/auth/verify", json={"token": token})
    headers = {"Authorization": f"Bearer {verified.json()['session_token']}"}

    request = (await client.get("/api/v1/customer/overview", headers=headers)).json()["requests"][0]
    assert request["slots_total"] == 5  # never the number of installers told

    lead = await _lead_of(db, installers[1])
    conversation = (await _start(client, installers[1], lead)).json()["id"]
    await client.post(
        f"{BASE}/conversations/{conversation}/quotes",
        json=OFFER,
        headers=auth_headers(installers[1].user),
    )
    detail = (
        await client.get(f"/api/v1/customer/requests/{request['id']}", headers=headers)
    ).json()
    assert [item["installer"]["business_name"] for item in detail["installers"]] == ["Installer 1"]
    assert len(detail["quotes"]) == 1
