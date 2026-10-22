"""Quote requests: validation, matching and notifications."""

import re

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core import security
from app.core.enums import InstallerStatus, QuoteStatus
from app.models import Installer, QuoteMatch, QuoteRequest
from tests.helpers import LEEDS, SALFORD, STOCKPORT, Fakes, Plan, create_installer, quote_payload


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
    assert body == {
        "reference": body["reference"],
        "postcode": "M1 1AA",
        "matched_installers": 5,
        "held": False,
    }

    # Everyone approved who covers the address is told (Free included, last); pending
    # listings and installers whose circle does not reach the address are not.
    expected = [
        "Premium Manchester",
        "Premium Stockport",
        "Pro Salford",
        "Pro Stockport",
        "Free Manchester",
    ]
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
    assert [email.template for email in leads] == ["new_lead"] * 5
    assert [email.to for email in leads] == [
        "premium-manchester@example.com",
        "premium-stockport@example.com",
        "pro-salford@example.com",
        "pro-stockport@example.com",
        "free-manchester@example.com",
    ]
    # The installer email is deliberately thin: first name, town, service and timeframe,
    # never the customer's phone, email or answers, and a link to the exact lead.
    first = leads[0]
    assert first.subject == "New Customer Enquiry : EV charger installation in Manchester"
    assert first.reply_to is None
    premium = await db.scalar(
        select(QuoteMatch)
        .join(QuoteMatch.installer)
        .where(Installer.business_name == "Premium Manchester")
    )
    assert (
        first.context.items()
        >= {
            "first_name": "Sam",
            "location": "Manchester",
            "service": "EV charger installation",
            "job": "install an EV charger",
            "timeframe": "Within a month",
            "max_quotes": 5,
            "url": f"http://localhost:5173/leads/{premium.id}",
        }.items()
    )


async def test_every_eligible_installer_is_notified_however_many_there_are(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    for index in range(7):
        await create_installer(db, f"Installer {index}")
    await create_installer(db, "Free Installer", plan=Plan.FREE)
    response = await client.post("/api/v1/quotes", json=quote_payload())
    assert response.json()["matched_installers"] == 8
    assert await db.scalar(select(func.count()).select_from(QuoteMatch)) == 8
    assert len(fakes.emails.of("new_lead")) == 8
    # Free installers are told too: the email is how they learn to upgrade.
    assert "free-installer@example.com" in [e.to for e in fakes.emails.of("new_lead")]


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
        assert response.json()["matched_installers"] == 2
    # A Free installer asked for by name gets no priority: the Pro one still comes first.
    assert (await _matched_names(db))[:2] == ["Pro Manchester", "Free Manchester"]


async def test_unmatched_quote_notifies_support(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    await create_installer(db, "Pending Manchester", status=InstallerStatus.PENDING)
    await create_installer(db, "Suspended Manchester", status=InstallerStatus.SUSPENDED)
    await create_installer(db, "Rejected Manchester", status=InstallerStatus.REJECTED)
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


async def test_phone_number_is_optional(client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession):
    await create_installer(db, "Pro Manchester")
    for phone in ("", "   ", None):
        response = await client.post("/api/v1/quotes", json=quote_payload(phone=phone))
        assert response.status_code == 201, phone
    without_field = quote_payload()
    del without_field["phone"]
    assert (await client.post("/api/v1/quotes", json=without_field)).status_code == 201

    phones = (await db.scalars(select(QuoteRequest.phone))).all()
    assert phones == [None, None, None, None]
    # The installer email never carries contact details, so it renders the same without one.
    lead = fakes.emails.of("new_lead")[0]
    assert "phone" not in str(lead.context)
    rendered = fakes.emails._renderer.render(lead).get_body(preferencelist=("plain",))
    assert "Customer: Sam" in rendered.get_content()

    # A number that is given must still be a valid one.
    invalid = await client.post("/api/v1/quotes", json=quote_payload(phone="12345"))
    assert invalid.status_code == 422
    assert list(invalid.json()["error"]["fields"]) == ["phone"]


async def test_homeowner_email_is_the_same_whether_or_not_installers_matched(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    """One fixed email: it never says how many installers, or which, got the request."""
    await create_installer(db, "Pro Manchester Electrical", plan=Plan.PRO)
    assert (await client.post("/api/v1/quotes", json=quote_payload())).status_code == 201
    far = quote_payload(postcode="LS1 4AP")  # nobody covers Leeds
    assert (await client.post("/api/v1/quotes", json=far)).status_code == 201

    matched, unmatched = fakes.emails.of("quote_confirmation")
    assert matched.context["installer_names"]
    assert not unmatched.context["installer_names"]

    def body(email, kind: str) -> str:
        part = fakes.emails._renderer.render(email).get_body(preferencelist=(kind,))
        text = part.get_content()
        for private in (email.context["reference"], email.context["link"]):
            text = text.replace(private, "PRIVATE")
        return text

    for kind in ("plain", "html"):
        first, second = body(matched, kind), body(unmatched, kind)
        assert "Pro Manchester Electrical" not in first
        assert "shared your request with" not in first
        assert "its way to qualified, vetted electricians" in first
        assert "We'll email you as soon as an installer responds." in first
        assert "choosing the best" not in second
        # Apart from the answers' own text, the two emails read the same.
        assert first.split("Here is what you told us")[0].replace(
            matched.context["first_name"], "X"
        ) == second.split("Here is what you told us")[0].replace(
            unmatched.context["first_name"], "X"
        )


async def test_honeypot_submissions_look_successful_but_store_nothing(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    await create_installer(db, "Pro Manchester")
    response = await client.post(
        "/api/v1/quotes", json=quote_payload(website="https://spam.example")
    )
    assert response.status_code == 201
    assert re.fullmatch(r"PAS-[A-Z2-9]{6}", response.json()["reference"])
    assert set(response.json()) == {"reference", "postcode", "matched_installers", "held"}
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


def test_installer_email_follows_the_service_of_the_request():
    """Subject and wording follow the request's service, so new services need no email change."""
    import uuid
    from types import SimpleNamespace

    from app.core.enums import Service, Timing
    from app.services import email as emails

    quote = SimpleNamespace(
        first_name="Gemma",
        district="Romford",
        postcode="RM1 1AA",
        timing=Timing.WITHIN_2_WEEKS,
        service=Service.SMART_HOME,
    )
    installer = SimpleNamespace(business_name="Any")
    mail = emails.new_lead(quote, installer, "a@example.com", uuid.uuid4(), 5)
    assert mail.subject == "New Customer Enquiry : Smart home in Romford"
    assert mail.context["service"] == "Smart home"
    assert mail.context["job"] == "help with smart home"
