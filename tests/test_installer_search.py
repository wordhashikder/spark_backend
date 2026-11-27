"""The /search/ page's API: filters, plan order with hourly rotation, and the plan rules."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import InstallerStatus, Role, StaffRole
from app.services.installer_search import ROTATION_SECONDS, SearchQuery, search
from tests.helpers import (
    LEEDS,
    STOCKPORT,
    FakeGeocoder,
    Plan,
    auth_headers,
    create_installer,
    create_user,
)

SEARCH = "/api/v1/installers/search"


async def _names(client: httpx.AsyncClient, **params) -> list[str]:
    response = await client.get(SEARCH, params=params)
    assert response.status_code == 200, response.text
    return [item["business_name"] for item in response.json()["items"]]


async def test_filters_combine_and_only_approved_installers_are_found(
    client: httpx.AsyncClient, db: AsyncSession
):
    await create_installer(db, "Volt Brothers", services=("ev_charger_installation",))
    await create_installer(
        db, "Bright Sparks", services=("solar_battery",), accreditations=("niceic",)
    )
    await create_installer(db, "Hidden Ltd", status=InstallerStatus.PENDING)
    await create_installer(
        db, "Leeds Charging", at=LEEDS, location="leeds", services=("ev_charger_installation",)
    )

    # Company name only.
    assert await _names(client, company="volt") == ["Volt Brothers"]
    # General search: name, service label and accreditation all count.
    assert await _names(client, q="bright") == ["Bright Sparks"]
    assert await _names(client, q="solar") == ["Bright Sparks"]
    assert await _names(client, q="niceic") == ["Bright Sparks"]
    # Service and accreditation filters (the URL's `?service=...`).
    assert set(await _names(client, service="ev_charger_installation")) == {
        "Volt Brothers",
        "Leeds Charging",
    }
    assert await _names(client, accreditation="niceic") == ["Bright Sparks"]
    # A town: the same rule as its page, so Manchester installers only.
    assert set(await _names(client, location="manchester")) >= {"Volt Brothers", "Bright Sparks"}
    assert "Leeds Charging" not in await _names(client, location="manchester")
    assert await _names(client, location="leeds", service="ev_charger_installation") == [
        "Leeds Charging"
    ]
    # Pending installers never appear, even by name.
    assert await _names(client, q="hidden") == []
    # A wildcard typed by a visitor is text, not a pattern.
    assert await _names(client, q="%") == []


async def test_a_postcode_finds_installers_within_the_distance(
    client: httpx.AsyncClient, db: AsyncSession
):
    await create_installer(db, "Manchester Volt")
    await create_installer(db, "Stockport Volt", at=STOCKPORT)
    await create_installer(db, "Leeds Volt", at=LEEDS, location="leeds")

    near = await _names(client, q="m1 1aa", distance=10)
    assert set(near) == {"Manchester Volt", "Stockport Volt"}
    wide = await _names(client, q="M1 1AA", distance=50)
    assert set(wide) == {"Manchester Volt", "Stockport Volt", "Leeds Volt"}


async def test_an_unknown_postcode_is_reported(client: httpx.AsyncClient):
    response = await client.get(SEARCH, params={"q": "ZZ9 9ZZ"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "postcode_not_found"


async def test_results_go_premium_then_pro_then_free(client: httpx.AsyncClient, db: AsyncSession):
    await create_installer(db, "Free Sparks", plan=Plan.FREE)
    await create_installer(db, "Premium Sparks", plan=Plan.PREMIUM)
    await create_installer(db, "Pro Sparks", plan=Plan.PRO)
    assert await _names(client) == ["Premium Sparks", "Pro Sparks", "Free Sparks"]


async def test_installers_rotate_each_hour_inside_their_plan(db: AsyncSession):
    for index in range(12):
        await create_installer(db, f"Pro {index:02d}", plan=Plan.PRO)
    await create_installer(db, "Free One", plan=Plan.FREE)
    geocoder = FakeGeocoder()

    async def order(now: float, **paging) -> list[str]:
        found, _ = await search(
            db,
            SearchQuery(),
            geocoder,
            offset=paging.get("offset", 0),
            limit=paging.get("limit", 50),
            now=now,
        )
        return [installer.business_name for installer in found]

    hour = 10 * ROTATION_SECONDS
    first = await order(hour)
    # The same hour gives the same order, whenever it is asked.
    assert await order(hour + ROTATION_SECONDS - 1) == first
    # The next hour shuffles the Pro group; Free stays below it.
    second = await order(hour + ROTATION_SECONDS)
    assert second != first
    assert set(second[:12]) == {f"Pro {index:02d}" for index in range(12)}
    assert first[-1] == second[-1] == "Free One"
    # Paging through an hour is stable: the pages add up to the full list.
    paged = await order(hour, offset=0, limit=5) + await order(hour, offset=5, limit=50)
    assert paged == first


async def test_every_plan_shows_all_services_and_the_website_link_follows_the_plan(
    client: httpx.AsyncClient, db: AsyncSession
):
    everything = (
        "ev_charger_installation",
        "domestic_electrical",
        "commercial_electrical",
        "solar_battery",
    )
    free = await create_installer(db, "Free Sparks", plan=Plan.FREE, services=everything)
    pro = await create_installer(db, "Pro Sparks", plan=Plan.PRO, services=everything)
    free.website_url = "https://free.example.com/"
    pro.website_url = "https://pro.example.com/"
    await db.commit()

    free_page = (await client.get(f"/api/v1/installers/{free.slug}")).json()
    pro_page = (await client.get(f"/api/v1/installers/{pro.slug}")).json()
    # All four services on the Free plan too.
    assert free_page["services"] == list(everything)
    assert pro_page["services"] == list(everything)
    # The link: Pro and Premium only, never in the Free profile's data at all.
    assert free_page["website_url"] is None
    assert pro_page["website_url"] == "https://pro.example.com/"

    # The team can turn it on for Free, and off for Pro, from Dashboard > Plans.
    owner = auth_headers(await create_user(db, role=Role.ADMIN, staff_role=StaffRole.OWNER))
    for plan, on in (("free", True), ("pro", False)):
        response = await client.patch(
            f"/api/v1/admin/plans/{plan}", headers=owner, json={"shows_website_link": on}
        )
        assert response.status_code == 200, response.text
        assert response.json()["shows_website_link"] is on
    assert (await client.get(f"/api/v1/installers/{free.slug}")).json()["website_url"] == (
        "https://free.example.com/"
    )
    assert (await client.get(f"/api/v1/installers/{pro.slug}")).json()["website_url"] is None
