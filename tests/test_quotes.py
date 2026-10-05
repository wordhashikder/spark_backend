"""Quote requests: validation, matching and notifications."""

import re

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core import security
from app.core.enums import InstallerStatus, Plan, QuoteStatus
from app.models import QuoteMatch, QuoteRequest
from tests.helpers import LEEDS, SALFORD, STOCKPORT, Fakes, create_installer, quote_payload


async def _matched_names(db: AsyncSession) -> list[str]:
    matches = await db.scalars(
        select(QuoteMatch).options(joinedload(QuoteMatch.installer)).order_by(QuoteMatch.id)
    )
    return [match.installer.business_name for match in matches]


async def test_quote_is_matched_by_plan_then_distance(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    await create_installer(db, "Pro Stockport", at=STOCKPORT, location="stockport")
    await create_installer(db, "Pro Salford", at=SALFORD, location="salford")
    await create_installer(
        db, "Premium Stockport", at=STOCKPORT, location="stockport", plan=Plan.PREMIUM
    )
    await create_installer(db, "Premium Manchester", plan=Plan.PREMIUM)
    await create_installer(db, "Free Manchester", plan=Plan.FREE)
    await create_installer(db, "Pending Manchester", status=InstallerStatus.PENDING)
    await create_installer(db, "Pro Leeds", at=LEEDS, location="leeds")
    await create_installer(
        db, "Small Radius Stockport", at=STOCKPORT, location="stockport", radius=3
    )

    response = await client.post("/api/v1/quotes", json=quote_payload())
    assert response.status_code == 201
    body = response.json()
    assert re.fullmatch(r"PAS-[A-HJ-KM-NP-Z2-9]{6}", body["reference"])
    assert body == {"reference": body["reference"], "postcode": "M1 1AA", "matched_installers": 4}

    expected = ["Premium Manchester", "Premium Stockport", "Pro Salford", "Pro Stockport"]
    assert await _matched_names(db) == expected

    quote = await db.scalar(select(QuoteRequest))
    assert quote.status is QuoteStatus.MATCHED
    assert (quote.district, quote.region) == ("Manchester", "North West")
    assert quote.consent_at is not None
    assert quote.ip_hash == security.hash_ip("127.0.0.1")
    assert "127.0.0.1" not in quote.ip_hash

    confirmation, *leads = fakes.emails.sent
    assert (confirmation.template, confirmation.to) == ("quote_confirmation", "sam@example.com")
    assert confirmation.context["installer_names"] == expected
    assert ("Timing", "Within a month") in confirmation.context["answers"]
    assert [email.template for email in leads] == ["new_lead"] * 4
    assert [email.to for email in leads] == [
        "premium-manchester@example.com",
        "premium-stockport@example.com",
        "pro-salford@example.com",
        "pro-stockport@example.com",
    ]
    assert leads[0].context["customer"] == {
        "first_name": "Sam",
        "email": "sam@example.com",
        "phone": "07700 900123",
    }


async def test_at_most_five_installers_are_matched(client: httpx.AsyncClient, db: AsyncSession):
    for index in range(7):
        await create_installer(db, f"Installer {index}")
    response = await client.post("/api/v1/quotes", json=quote_payload())
    assert response.json()["matched_installers"] == 5
    assert await db.scalar(select(func.count()).select_from(QuoteMatch)) == 5


async def test_better_rated_installers_win_ties(client: httpx.AsyncClient, db: AsyncSession):
    await create_installer(db, "Unrated")
    await create_installer(db, "Four Stars", rating=4.0, review_count=3)
    await create_installer(db, "Five Stars", rating=5.0, review_count=1)
    await client.post("/api/v1/quotes", json=quote_payload())
    assert await _matched_names(db) == ["Five Stars", "Four Stars", "Unrated"]


async def test_direct_quote_always_includes_the_requested_installer_first(
    client: httpx.AsyncClient, db: AsyncSession
):
    await create_installer(db, "Premium Manchester", plan=Plan.PREMIUM)
    far_away = await create_installer(db, "Pro Leeds", at=LEEDS, location="leeds")

    response = await client.post("/api/v1/quotes", json=quote_payload(installer_slug=far_away.slug))
    assert response.json()["matched_installers"] == 2
    assert await _matched_names(db) == ["Pro Leeds", "Premium Manchester"]
    quote = await db.scalar(select(QuoteRequest))
    assert quote.target_installer_id == far_away.id


async def test_direct_quote_to_a_free_installer_falls_back_to_normal_matching(
    client: httpx.AsyncClient, db: AsyncSession
):
    free = await create_installer(db, "Free Manchester", plan=Plan.FREE)
    await create_installer(db, "Pro Manchester")
    for slug in (free.slug, "no-such-installer"):
        response = await client.post("/api/v1/quotes", json=quote_payload(installer_slug=slug))
        assert response.status_code == 201
        assert response.json()["matched_installers"] == 1
    assert set(await _matched_names(db)) == {"Pro Manchester"}


async def test_unmatched_quote_notifies_support(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    await create_installer(db, "Free Manchester", plan=Plan.FREE)
    response = await client.post("/api/v1/quotes", json=quote_payload())
    assert response.status_code == 201
    assert response.json()["matched_installers"] == 0

    quote = await db.scalar(select(QuoteRequest))
    assert quote.status is QuoteStatus.UNMATCHED
    confirmation, internal = fakes.emails.sent
    assert confirmation.context["installer_names"] == []
    assert (internal.template, internal.to) == ("quote_unmatched", "support@pickasparky.test")
    assert internal.context["geocoded"] is True


async def test_quote_is_still_accepted_when_geocoding_is_down(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    await create_installer(db, "Pro Manchester")
    fakes.geocoder.unavailable = True

    response = await client.post("/api/v1/quotes", json=quote_payload())
    assert response.status_code == 201
    assert response.json()["matched_installers"] == 0
    assert response.json()["postcode"] == "M1 1AA"

    quote = await db.scalar(select(QuoteRequest))
    assert quote.status is QuoteStatus.UNMATCHED
    assert (quote.latitude, quote.longitude, quote.district) == (None, None, None)
    assert fakes.emails.of("quote_unmatched")[0].context["geocoded"] is False


async def test_followup_must_match_the_existing_charger_branch(client: httpx.AsyncClient):
    mismatched = [
        ("replace", "already_bought"),
        ("no", "supply_and_install"),
        ("add_another", "recommend_replacement"),
    ]
    for existing, followup in mismatched:
        response = await client.post(
            "/api/v1/quotes",
            json=quote_payload(existing_charger=existing, charger_followup=followup),
        )
        assert response.status_code == 422, (existing, followup)
        assert list(response.json()["error"]["fields"]) == ["charger_followup"]

    valid = [
        ("replace", "fit_customer_charger"),
        ("replace", "not_sure"),
        ("add_another", "not_sure"),
    ]
    for existing, followup in valid:
        response = await client.post(
            "/api/v1/quotes",
            json=quote_payload(existing_charger=existing, charger_followup=followup),
        )
        assert response.status_code == 201, (existing, followup)


async def test_quote_validation(client: httpx.AsyncClient, db: AsyncSession):
    no_consent = await client.post("/api/v1/quotes", json=quote_payload(consent=False))
    assert no_consent.status_code == 422
    assert list(no_consent.json()["error"]["fields"]) == ["consent"]

    unknown_postcode = await client.post("/api/v1/quotes", json=quote_payload(postcode="ZZ9 9ZZ"))
    assert unknown_postcode.status_code == 422
    assert unknown_postcode.json()["error"]["fields"] == {
        "postcode": "We could not find that postcode."
    }

    invalid = await client.post(
        "/api/v1/quotes",
        json=quote_payload(
            postcode="nonsense",
            phone="call me",
            email="sam@",
            timing="whenever",
            first_name=" ",
            notes="x" * 1001,
            vehicle="y" * 121,
        ),
    )
    assert invalid.status_code == 422
    assert set(invalid.json()["error"]["fields"]) == {
        "postcode",
        "phone",
        "email",
        "timing",
        "first_name",
        "notes",
        "vehicle",
    }
    assert await db.scalar(select(func.count()).select_from(QuoteRequest)) == 0


async def test_optional_answers_may_be_omitted(client: httpx.AsyncClient, db: AsyncSession):
    payload = quote_payload(vehicle="", vehicle_undecided=True, notes=None)
    assert (await client.post("/api/v1/quotes", json=payload)).status_code == 201
    quote = await db.scalar(select(QuoteRequest))
    assert (quote.vehicle, quote.vehicle_undecided, quote.notes) == (None, True, None)


async def test_honeypot_submissions_look_successful_but_store_nothing(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    await create_installer(db, "Pro Manchester")
    response = await client.post(
        "/api/v1/quotes", json=quote_payload(website="https://spam.example")
    )
    assert response.status_code == 201
    assert re.fullmatch(r"PAS-[A-Z2-9]{6}", response.json()["reference"])
    assert set(response.json()) == {"reference", "postcode", "matched_installers"}
    assert await db.scalar(select(func.count()).select_from(QuoteRequest)) == 0
    assert fakes.emails.sent == []


async def test_visitor_ip_is_taken_from_the_frontend_only_with_the_internal_token(
    client: httpx.AsyncClient, db: AsyncSession
):
    forwarded = {"X-Client-IP": "203.0.113.9"}
    await client.post("/api/v1/quotes", json=quote_payload(), headers=forwarded)
    await client.post(
        "/api/v1/quotes",
        json=quote_payload(),
        headers=forwarded | {"X-Internal-Token": "test-internal-key"},
    )
    await client.post(
        "/api/v1/quotes",
        json=quote_payload(),
        headers=forwarded | {"X-Internal-Token": "wrong-key"},
    )
    hashes = (
        await db.scalars(select(QuoteRequest.ip_hash).order_by(QuoteRequest.created_at))
    ).all()
    peer, visitor = security.hash_ip("127.0.0.1"), security.hash_ip("203.0.113.9")
    assert hashes == [peer, visitor, peer]
