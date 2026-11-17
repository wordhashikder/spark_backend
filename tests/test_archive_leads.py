"""Archiving quote requests and profile enquiries in the back office.

Archive tidies the team's lists and "needs attention" counts and keeps the record. It never
changes what installers or homeowners see, and it can be undone.
"""

from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import QuoteStatus, Role, StaffRole
from app.models import InstallerEnquiry, QuoteRequest
from tests.helpers import auth_headers, create_installer, create_user, quote_payload

ADMIN = "/api/v1/admin"


def _enquiry(**overrides: Any) -> dict[str, Any]:
    return {
        "name": "Sam Jones",
        "email": "sam@example.com",
        "phone": "",
        "message": "Can you fit a 7kW charger next week?",
        **overrides,
    }


async def _owner(db: AsyncSession) -> dict[str, str]:
    return auth_headers(await create_user(db, role=Role.ADMIN, staff_role=StaffRole.OWNER))


async def _held_request(client: httpx.AsyncClient, db: AsyncSession) -> QuoteRequest:
    """A request nobody covers, so it waits for the team (counts toward the bell)."""
    assert (await client.post("/api/v1/quotes", json=quote_payload())).status_code == 201
    quote = await db.scalar(select(QuoteRequest))
    assert quote is not None
    quote.status = QuoteStatus.UNMATCHED
    await db.commit()
    return quote


async def test_archiving_a_request_hides_it_from_lists_and_counts_and_restoring_brings_it_back(
    client: httpx.AsyncClient, db: AsyncSession
):
    owner = await _owner(db)
    quote = await _held_request(client, db)
    url = f"{ADMIN}/quotes/{quote.id}"

    before = (await client.get(f"{ADMIN}/quotes/stages", headers=owner)).json()
    assert (before["all"], before["held"], before["archived"]) == (1, 1, 0)
    assert (await client.get(f"{ADMIN}/nav", headers=owner)).json()["leads"] == 1

    archived = await client.post(f"{url}/archive", headers=owner)
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None

    # Gone from the working list, the "Waiting for you" list, the chips and the bell ...
    assert (await client.get(f"{ADMIN}/quotes", headers=owner)).json()["total"] == 0
    waiting = await client.get(f"{ADMIN}/quotes", params={"waiting": "true"}, headers=owner)
    assert waiting.json()["total"] == 0
    stages = (await client.get(f"{ADMIN}/quotes/stages", headers=owner)).json()
    assert (stages["all"], stages["open"], stages["held"], stages["archived"]) == (0, 0, 0, 1)
    assert (await client.get(f"{ADMIN}/nav", headers=owner)).json()["leads"] == 0
    overview = (await client.get(f"{ADMIN}/overview", headers=owner)).json()
    assert overview["held_leads"] == 0
    assert overview["unmatched_leads"] == 0
    assert overview["recent_leads"] == []
    # ... but kept: the Archived view lists it, and it still opens by id (notification links).
    shown = (await client.get(f"{ADMIN}/quotes", params={"archived": "true"}, headers=owner)).json()
    assert [item["id"] for item in shown["items"]] == [str(quote.id)]
    assert (await client.get(url, headers=owner)).json()["archived_at"] is not None

    # Archiving twice changes nothing.
    again = await client.post(f"{url}/archive", headers=owner)
    assert again.json()["archived_at"] == archived.json()["archived_at"]

    restored = await client.post(f"{url}/restore", headers=owner)
    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None
    assert (await client.get(f"{ADMIN}/quotes", headers=owner)).json()["total"] == 1
    assert (await client.get(f"{ADMIN}/nav", headers=owner)).json()["leads"] == 1
    again = (await client.get(f"{ADMIN}/quotes/stages", headers=owner)).json()
    assert (again["all"], again["held"], again["archived"]) == (1, 1, 0)


async def test_archived_search_and_unknown_ids(client: httpx.AsyncClient, db: AsyncSession):
    owner = await _owner(db)
    quote = await _held_request(client, db)
    await client.post(f"{ADMIN}/quotes/{quote.id}/archive", headers=owner)

    # The search box works inside whichever view is open.
    found = await client.get(
        f"{ADMIN}/quotes", params={"archived": "true", "q": quote.reference}, headers=owner
    )
    assert found.json()["total"] == 1
    active = await client.get(f"{ADMIN}/quotes", params={"q": quote.reference}, headers=owner)
    assert active.json()["total"] == 0

    missing = "00000000-0000-0000-0000-000000000000"
    assert (
        await client.post(f"{ADMIN}/quotes/{missing}/archive", headers=owner)
    ).status_code == 404
    assert (
        await client.post(f"{ADMIN}/quotes/{missing}/restore", headers=owner)
    ).status_code == 404


async def test_archiving_only_tidies_the_back_office(client: httpx.AsyncClient, db: AsyncSession):
    """The installer still has the lead, and the request's own status is unchanged."""
    owner = await _owner(db)
    installer = await create_installer(db, "Manchester Installer")
    assert (await client.post("/api/v1/quotes", json=quote_payload())).status_code == 201
    quote = await db.scalar(select(QuoteRequest))
    assert quote is not None
    assert quote.status == QuoteStatus.MATCHED

    assert (
        await client.post(f"{ADMIN}/quotes/{quote.id}/archive", headers=owner)
    ).status_code == 200

    await db.refresh(quote)
    assert quote.status == QuoteStatus.MATCHED
    leads = await client.get("/api/v1/installers/me/leads", headers=auth_headers(installer.user))
    assert leads.status_code == 200
    assert leads.json()["total"] == 1
    # Still counted in the history the overview's totals are built from.
    overview = (await client.get(f"{ADMIN}/overview", headers=owner)).json()
    assert overview["leads"]["value"] == 1


async def test_archiving_needs_leads_access(client: httpx.AsyncClient, db: AsyncSession):
    quote = await _held_request(client, db)
    support = auth_headers(await create_user(db, role=Role.ADMIN, staff_role=StaffRole.SUPPORT))
    editor = auth_headers(await create_user(db, role=Role.ADMIN, staff_role=StaffRole.EDITOR))
    installer = await create_installer(db, "Manchester Installer")

    url = f"{ADMIN}/quotes/{quote.id}/archive"
    assert (await client.post(url, headers=support)).status_code == 200  # Support has leads
    assert (await client.post(url.replace("archive", "restore"), headers=editor)).status_code == 403
    assert (await client.post(url, headers=auth_headers(installer.user))).status_code == 403
    assert (await client.post(url)).status_code == 401


async def test_archiving_profile_enquiries(client: httpx.AsyncClient, db: AsyncSession):
    owner = await _owner(db)
    free = await create_installer(db, "Free Manchester", plan="free")
    mine = await create_installer(db, "Pro Manchester", location="manchester")
    for installer in (free, mine):
        sent = await client.post(f"/api/v1/installers/{installer.slug}/enquiries", json=_enquiry())
        assert sent.status_code == 202
    team_one = await db.scalar(
        select(InstallerEnquiry).where(InstallerEnquiry.installer_id == free.id)
    )
    assert team_one is not None
    assert (await client.get(f"{ADMIN}/overview", headers=owner)).json()["enquiries_for_team"] == 1

    archived = await client.post(f"{ADMIN}/enquiries/{team_one.id}/archive", headers=owner)
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None

    active = (await client.get(f"{ADMIN}/enquiries", headers=owner)).json()
    assert active["total"] == 1
    assert active["items"][0]["installer_name"] == "Pro Manchester"
    assert (await client.get(f"{ADMIN}/overview", headers=owner)).json()["enquiries_for_team"] == 0
    shown = (
        await client.get(f"{ADMIN}/enquiries", params={"archived": "true"}, headers=owner)
    ).json()
    assert [item["id"] for item in shown["items"]] == [str(team_one.id)]
    assert shown["items"][0]["email"] == "sam@example.com"

    # Installers' own enquiry lists are unaffected, and restoring puts it back.
    mine_list = await client.get("/api/v1/installers/me/enquiries", headers=auth_headers(mine.user))
    assert mine_list.json()["total"] == 1
    restored = await client.post(f"{ADMIN}/enquiries/{team_one.id}/restore", headers=owner)
    assert restored.json()["archived_at"] is None
    assert (await client.get(f"{ADMIN}/enquiries", headers=owner)).json()["total"] == 2

    missing = "00000000-0000-0000-0000-000000000000"
    assert (
        await client.post(f"{ADMIN}/enquiries/{missing}/archive", headers=owner)
    ).status_code == 404
    editor = auth_headers(await create_user(db, role=Role.ADMIN, staff_role=StaffRole.EDITOR))
    forbidden = await client.post(f"{ADMIN}/enquiries/{team_one.id}/archive", headers=editor)
    assert forbidden.status_code == 403
