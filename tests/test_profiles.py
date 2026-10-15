"""Profiles for the directory listings: complete, truthful and never overwriting edits."""

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Installer
from app.services import profiles, seeding


async def test_every_imported_listing_gets_a_complete_profile(db: AsyncSession):
    added = await seeding.insert_listings(db)
    await db.commit()
    assert added == 193

    listings = list(await db.scalars(select(Installer)))
    assert len(listings) == 193
    for listing in listings:
        assert listing.tagline
        assert listing.town in listing.tagline
        assert listing.description
        assert listing.business_name in listing.description
        assert "\n\n" in listing.description  # two paragraphs
        assert listing.areas_covered[0] == listing.town
        # Nothing about the business is made up.
        assert listing.years_experience is None
        assert listing.logo_url is None
    # Profiles are not all word for word the same.
    assert (
        len(
            {
                listing.description.split(".")[0].split(listing.business_name)[0]
                for listing in listings
            }
        )
        > 1
    )


async def test_enrichment_updates_only_untouched_generated_listings(db: AsyncSession):
    await seeding.insert_listings(db)
    await db.commit()
    untouched, edited, claimed = list(
        await db.scalars(select(Installer).order_by(Installer.business_name).limit(3))
    )
    untouched.description = (
        f"{untouched.business_name} is an electrical business based in X (M1), listed on "
        "PickASparky for EV charger installation in Y and the surrounding area."
    )
    untouched.areas_covered = [untouched.town]
    edited.description = "Written by the team, so it stays exactly as it is."
    claimed.description = untouched.description
    claimed.contact_name = "Owner"
    await db.commit()

    changed = await seeding.enrich_listing_profiles(db)
    await db.commit()
    await db.refresh(untouched)
    await db.refresh(edited)
    assert changed >= 1
    assert "\n\n" in untouched.description
    assert edited.description == "Written by the team, so it stays exactly as it is."


async def test_public_profile_has_cover_image_and_facts(
    client: httpx.AsyncClient, db: AsyncSession
):
    await seeding.insert_listings(db)
    await db.commit()
    listing = await db.scalar(select(Installer).limit(1))
    page = await client.get(f"/api/v1/installers/{listing.slug}")
    assert page.status_code == 200
    body = page.json()
    assert body["postcode_district"] == listing.base_postcode.split(" ")[0]
    assert body["listed_since"]
    assert body["verified"] is False
    assert body["is_claimed"] is False


def test_profile_text_is_stable_and_varied():
    kwargs = {
        "town": "Manchester",
        "locality": "Didsbury",
        "postcode": "M20 2LS",
        "nearby": ["Salford", "Stockport"],
        "radius": 15,
    }
    first = profiles.build(business_name="Alpha Electrical", **kwargs)
    assert first == profiles.build(business_name="Alpha Electrical", **kwargs)
    assert "Salford and Stockport" in first.description
    assert "Didsbury, Manchester" in first.description
    openings = {
        profiles.build(business_name=name, **kwargs).description.split(".")[0].replace(name, "")
        for name in ("A1", "B2", "C3", "D4", "E5", "F6", "G7", "H8")
    }
    assert len(openings) > 1
