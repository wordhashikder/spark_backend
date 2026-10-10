"""Public directory, plan gating, locations and the installer's own profile."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import InstallerStatus, Plan
from tests.helpers import (
    LEEDS,
    PNG_BYTES,
    STOCKPORT,
    Fakes,
    auth_headers,
    create_installer,
)


async def test_listing_shows_only_approved_installers_in_rank_order(
    client: httpx.AsyncClient, db: AsyncSession
):
    await create_installer(db, "Free Listing", plan=Plan.FREE, rating=5.0, review_count=40)
    await create_installer(db, "Pro Listing", rating=4.2, review_count=3)
    await create_installer(db, "Premium Listing", plan=Plan.PREMIUM)
    await create_installer(db, "Pro Featured", featured=True)
    await create_installer(db, "Pending Listing", status=InstallerStatus.PENDING)
    await create_installer(db, "Suspended Listing", status=InstallerStatus.SUSPENDED)

    response = await client.get("/api/v1/installers")
    assert response.status_code == 200
    body = response.json()
    assert [item["business_name"] for item in body["items"]] == [
        "Premium Listing",
        "Pro Featured",
        "Pro Listing",
        "Free Listing",
    ]
    assert (body["total"], body["page"], body["pages"]) == (4, 1, 1)
    card = body["items"][2]
    assert card == {
        "slug": "pro-listing",
        "business_name": "Pro Listing",
        "logo_url": None,
        "town": "Manchester",
        "location_slug": "manchester",
        "rating_avg": 4.2,
        "review_count": 3,
        "plan": "pro",
        "is_featured": False,
        "verified": True,
        "is_claimed": True,
    }

    featured = await client.get("/api/v1/installers", params={"featured": "true"})
    assert [item["slug"] for item in featured.json()["items"]] == ["pro-featured"]


async def test_listing_is_paginated(client: httpx.AsyncClient, db: AsyncSession):
    for index in range(5):
        await create_installer(db, f"Installer {index}")

    response = await client.get("/api/v1/installers", params={"page": 2, "page_size": 2})
    body = response.json()
    assert (body["total"], body["page"], body["page_size"], body["pages"]) == (5, 2, 2, 3)
    assert len(body["items"]) == 2

    too_big = await client.get("/api/v1/installers", params={"page_size": 101})
    assert too_big.status_code == 422


async def test_location_filter_uses_coverage_and_home_location(
    client: httpx.AsyncClient, db: AsyncSession
):
    await create_installer(db, "Manchester Wide", radius=15)
    await create_installer(db, "Stockport Local", at=STOCKPORT, location="stockport", radius=2)
    await create_installer(db, "Leeds Local", at=LEEDS, location="leeds", radius=5)

    stockport = await client.get("/api/v1/installers", params={"location": "stockport"})
    assert {item["slug"] for item in stockport.json()["items"]} == {
        "manchester-wide",
        "stockport-local",
    }
    manchester = await client.get("/api/v1/installers", params={"location": "manchester"})
    assert [item["slug"] for item in manchester.json()["items"]] == ["manchester-wide"]

    unknown = await client.get("/api/v1/installers", params={"location": "atlantis"})
    assert unknown.status_code == 404


async def test_public_profile_is_gated_by_plan(client: httpx.AsyncClient, db: AsyncSession):
    await create_installer(db, "Paid Profile", accreditations=("ozev", "niceic"))
    await create_installer(db, "Free Profile", plan=Plan.FREE)
    await create_installer(db, "Hidden Profile", status=InstallerStatus.PENDING)

    paid = (await client.get("/api/v1/installers/paid-profile")).json()
    assert paid["services"] == ["ev_charger_installation", "domestic_electrical", "smart_home"]
    assert [item["scheme"] for item in paid["accreditations"]] == ["ozev", "niceic"]
    assert paid["areas_covered"] == ["Manchester", "Salford"]
    assert paid["accepts_direct_quotes"] is True
    assert paid["coverage"] == {"latitude": 53.4808, "longitude": -2.2426, "radius_miles": 15}

    free = (await client.get("/api/v1/installers/free-profile")).json()
    assert free["services"] == ["ev_charger_installation", "domestic_electrical"]
    assert free["accreditations"] == []
    assert free["areas_covered"] == []
    assert free["photos"] == []
    assert free["accepts_direct_quotes"] is False
    # Private fields never appear on the public profile.
    assert not {"phone", "contact_name", "base_postcode", "status"} & free.keys()

    assert (await client.get("/api/v1/installers/hidden-profile")).status_code == 404
    assert (await client.get("/api/v1/installers/hidden-profile/reviews")).status_code == 404


async def test_similar_installers_are_nearest_first(client: httpx.AsyncClient, db: AsyncSession):
    await create_installer(db, "Origin")
    await create_installer(db, "Far Away", at=LEEDS, location="leeds")
    await create_installer(db, "Close By", at=STOCKPORT, location="stockport")
    await create_installer(db, "Not Live", status=InstallerStatus.PENDING)

    response = await client.get("/api/v1/installers/origin/similar")
    assert [item["slug"] for item in response.json()] == ["close-by", "far-away"]


async def test_locations_report_installer_counts(client: httpx.AsyncClient, db: AsyncSession):
    await create_installer(db, "Manchester Wide", radius=15)
    await create_installer(db, "Pending One", status=InstallerStatus.PENDING)

    locations = (await client.get("/api/v1/locations")).json()
    assert len(locations) == 34
    assert [item["name"] for item in locations] == sorted(item["name"] for item in locations)
    counts = {item["slug"]: item["installer_count"] for item in locations}
    assert (counts["manchester"], counts["stockport"], counts["london"]) == (1, 1, 0)

    detail = (await client.get("/api/v1/locations/manchester")).json()
    assert detail["installer_count"] == 1
    assert detail["image_url"] == "/images/locations/manchester.jpg"
    assert detail["intro"].startswith("Manchester is rapidly expanding")
    assert (await client.get("/api/v1/locations/atlantis")).status_code == 404


async def test_directory_is_the_same_curated_layout_everywhere(client: httpx.AsyncClient):
    directory = (await client.get("/api/v1/locations/directory")).json()
    groups = {
        name: [item["name"] for item in directory[name]]
        for name in ("nearby", "popular", "more_in_area", "other")
    }
    assert groups == {
        "nearby": [
            "Salford",
            "Trafford",
            "Stockport",
            "Oldham",
            "Bury",
            "Altrincham",
            "Rochdale",
            "Bolton",
        ],
        "popular": [
            "London",
            "Birmingham",
            "Leeds",
            "Liverpool",
            "Bristol",
            "Manchester",
            "Glasgow",
            "Edinburgh",
        ],
        "more_in_area": [
            "Warrington",
            "Macclesfield",
            "St Helens",
            "Blackburn",
            "Huddersfield",
            "Preston",
            "Crewe",
            "Bradford",
        ],
        "other": [
            "Brighton",
            "Cardiff",
            "Chester",
            "Coventry",
            "Leicester",
            "Newcastle",
            "Nottingham",
            "Sheffield",
        ],
    }
    listed = [name for group in groups.values() for name in group]
    assert len(listed) == len(set(listed)) == 32
    assert set(directory) == {"nearby", "popular", "more_in_area", "other"}
    # Older clients still send ?near=; the layout does not change with it.
    leeds = (await client.get("/api/v1/locations/directory", params={"near": "leeds"})).json()
    assert leeds == directory


async def test_postcode_lookup(client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession):
    await create_installer(db, "Covers Manchester")
    await create_installer(db, "Free Does Not Count", plan=Plan.FREE)

    found = await client.get("/api/v1/postcodes/m11aa")
    assert found.status_code == 200
    assert found.json() == {
        "postcode": "M1 1AA",
        "district": "Manchester",
        "region": "North West",
        "installers_in_range": 1,
    }

    malformed = await client.get("/api/v1/postcodes/not-a-postcode")
    assert malformed.status_code == 422
    assert "postcode" in malformed.json()["error"]["fields"]

    unknown = await client.get("/api/v1/postcodes/ZZ99 9ZZ")
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (404, "postcode_not_found")

    fakes.geocoder.unavailable = True
    down = await client.get("/api/v1/postcodes/M1 1AA")
    assert (down.status_code, down.json()["error"]["code"]) == (503, "geocoding_unavailable")


async def test_installer_reads_and_updates_their_own_profile(
    client: httpx.AsyncClient, db: AsyncSession
):
    installer = await create_installer(db, "My Business", plan=Plan.FREE)
    headers = auth_headers(installer.user)

    assert (await client.get("/api/v1/installers/me")).status_code == 401

    own = (await client.get("/api/v1/installers/me", headers=headers)).json()
    # The owner sees everything, whatever the plan shows publicly.
    assert len(own["services"]) == 3
    assert (own["status"], own["phone"], own["base_postcode"]) == (
        "approved",
        "0161 496 0000",
        "M1 1AA",
    )

    update = await client.patch(
        "/api/v1/installers/me",
        headers=headers,
        json={
            "tagline": "  Fast, tidy installs  ",
            "coverage_radius_miles": 25,
            "base_postcode": "sk1 3xe",
            "services": ["ev_charger_installation", "solar_battery"],
            "accreditations": [
                {"scheme": "ozev", "registration_number": "REG-1"},
                {"scheme": "napit", "registration_number": "NEW-9"},
            ],
        },
    )
    assert update.status_code == 200, update.text
    body = update.json()
    assert body["tagline"] == "Fast, tidy installs"
    assert (body["base_postcode"], body["town"], body["location_slug"]) == (
        "SK1 3XE",
        "Stockport",
        "stockport",
    )
    assert body["coverage"]["radius_miles"] == 25
    assert body["services"] == ["ev_charger_installation", "solar_battery"]
    # An unchanged entry keeps its verification; a new one starts unverified.
    assert {item["scheme"]: item["verified"] for item in body["accreditations"]} == {
        "ozev": True,
        "napit": False,
    }

    changed_number = await client.patch(
        "/api/v1/installers/me",
        headers=headers,
        json={"accreditations": [{"scheme": "ozev", "registration_number": "REG-2"}]},
    )
    assert changed_number.json()["accreditations"] == [
        {"scheme": "ozev", "registration_number": "REG-2", "verified": False}
    ]


async def test_profile_update_validation(client: httpx.AsyncClient, db: AsyncSession):
    installer = await create_installer(db, "Strict Business")
    headers = auth_headers(installer.user)

    async def fields(payload: dict) -> set[str]:
        response = await client.patch("/api/v1/installers/me", headers=headers, json=payload)
        assert response.status_code == 422, response.text
        return set(response.json()["error"]["fields"])

    assert await fields({"coverage_radius_miles": 500}) == {"coverage_radius_miles"}
    assert await fields({"services": ["time_travel"]}) == {"services"}
    assert await fields({"business_name": None}) == {"business_name"}
    assert await fields({"base_postcode": "ZZ99 9ZZ"}) == {"base_postcode"}
    assert await fields({"accreditations": [{"scheme": "ozev"}, {"scheme": "ozev"}]}) == {
        "accreditations"
    }

    # Clients can never grant themselves status, plan or verification.
    sneaky = await client.patch(
        "/api/v1/installers/me",
        headers=headers,
        json={"plan": "premium", "status": "approved", "is_featured": True},
    )
    assert sneaky.status_code in (200, 422)
    own = (await client.get("/api/v1/installers/me", headers=headers)).json()
    assert (own["plan"], own["is_featured"]) == ("pro", False)


async def test_media_uploads_respect_type_and_plan_limits(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    paid = await create_installer(db, "Paid Media")
    headers = auth_headers(paid.user)
    image = {"file": ("logo.png", PNG_BYTES, "image/png")}

    logo = await client.post("/api/v1/installers/me/logo", headers=headers, files=image)
    assert logo.status_code == 200, logo.text
    assert logo.json()["logo_url"] == "https://images.test/logos/image-1.png"

    replaced = await client.post("/api/v1/installers/me/logo", headers=headers, files=image)
    assert replaced.status_code == 200
    assert fakes.storage.deleted == ["logos/image-1"]

    # The declared content type is ignored: the bytes decide.
    disguised = {"file": ("photo.png", b"<script>alert(1)</script>", "image/png")}
    rejected = await client.post("/api/v1/installers/me/photos", headers=headers, files=disguised)
    assert (rejected.status_code, rejected.json()["error"]["code"]) == (
        415,
        "unsupported_media_type",
    )

    photo = await client.post(
        "/api/v1/installers/me/photos", headers=headers, files=image, data={"alt": "Wall charger"}
    )
    assert photo.status_code == 201, photo.text
    photo_id = photo.json()["id"]
    public = (await client.get("/api/v1/installers/paid-media")).json()
    assert [(item["id"], item["alt"]) for item in public["photos"]] == [(photo_id, "Wall charger")]

    deleted = await client.delete(f"/api/v1/installers/me/photos/{photo_id}", headers=headers)
    assert deleted.status_code == 204
    assert fakes.storage.deleted[-1].startswith("gallery/")

    free = await create_installer(db, "Free Media", plan=Plan.FREE)
    blocked = await client.post(
        "/api/v1/installers/me/photos", headers=auth_headers(free.user), files=image
    )
    assert (blocked.status_code, blocked.json()["error"]["code"]) == (403, "plan_limit_reached")
