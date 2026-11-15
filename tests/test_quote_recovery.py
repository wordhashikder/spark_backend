"""Quote requests received while the postcode lookup was down are matched once it is back."""

import asyncio
import logging
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionFactory
from app.core.enums import QuoteStatus
from app.models import PlatformSetting, QuoteMatch, QuoteRequest
from app.services import lead_stats, platform, quote_recovery
from tests.helpers import Fakes, create_installer, quote_payload


async def _post_during_outage(
    client: httpx.AsyncClient, fakes: Fakes, **overrides: object
) -> httpx.Response:
    fakes.geocoder.unavailable = True
    response = await client.post("/api/v1/quotes", json=quote_payload(**overrides))
    assert response.status_code == 201
    fakes.emails.sent.clear()
    return response


async def _recover(fakes: Fakes) -> int:
    return await quote_recovery.recover_pending(fakes.geocoder, fakes.emails, batch=10)


async def _quote(db: AsyncSession) -> QuoteRequest:
    db.expire_all()
    return await db.scalar(select(QuoteRequest))


async def test_a_waiting_request_stays_waiting_while_the_lookup_is_down(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession, caplog: pytest.LogCaptureFixture
):
    await create_installer(db, "Pro Manchester")
    await _post_during_outage(client, fakes)
    caplog.clear()

    assert await _recover(fakes) == 0

    # Still being down is expected, not an error to report.
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]

    assert (await _quote(db)).status is QuoteStatus.PENDING_LOCATION
    assert fakes.emails.sent == []


async def test_a_waiting_request_is_matched_when_the_lookup_returns(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_installer(db, "Pro Manchester")
    installer_id, installer_email = installer.id, installer.user.email
    await _post_during_outage(client, fakes)
    fakes.geocoder.unavailable = False

    assert await _recover(fakes) == 1

    quote = await _quote(db)
    assert quote.status is QuoteStatus.MATCHED
    assert (quote.postcode, quote.district) == ("M1 1AA", "Manchester")
    assert quote.latitude is not None
    lead = await db.scalar(select(QuoteMatch))
    assert lead.installer_id == installer_id
    (email,) = fakes.emails.sent
    assert (email.template, email.to) == ("new_lead", installer_email)
    assert email.from_name  # the Settings page was applied on the way out

    # Nothing is left to do, and a second pass never matches the request twice.
    assert await _recover(fakes) == 0
    assert await db.scalar(select(func.count()).select_from(QuoteMatch)) == 1


async def test_a_request_for_one_installer_still_goes_to_them(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    asked_for = await create_installer(db, "Asked For Manchester")
    asked_for_id, asked_for_slug = asked_for.id, asked_for.slug
    await create_installer(db, "Other Manchester")
    await _post_during_outage(client, fakes, installer_slug=asked_for_slug)
    fakes.geocoder.unavailable = False

    await _recover(fakes)

    quote = await _quote(db)
    assert quote.target_installer_id == asked_for_id
    matched = set(await db.scalars(select(QuoteMatch.installer_id)))
    assert asked_for_id in matched


async def test_a_postcode_the_lookup_does_not_know_is_unmatched_and_the_team_is_told(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    await create_installer(db, "Pro Manchester")
    await _post_during_outage(client, fakes, postcode="ZZ9 9ZZ")
    fakes.geocoder.unavailable = False

    assert await _recover(fakes) == 1

    assert (await _quote(db)).status is QuoteStatus.UNMATCHED
    (alert,) = fakes.emails.sent
    assert (alert.template, alert.to) == ("quote_unmatched", "support@pickasparky.test")
    assert alert.context["postcode_unknown"] is True


async def test_automatic_matching_off_holds_a_recovered_request_for_the_team(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    await create_installer(db, "Waiting Installer")
    db.add(PlatformSetting(key="lead_matching", data={"automatic": False, "max_installers": 3}))
    await db.commit()
    platform.clear_cache()
    await _post_during_outage(client, fakes)
    fakes.geocoder.unavailable = False

    await _recover(fakes)

    assert (await _quote(db)).status is QuoteStatus.NEW
    (alert,) = fakes.emails.sent
    assert alert.template == "quote_unmatched"
    assert alert.context["held"] is True


async def test_two_workers_never_match_the_same_request_twice(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    await create_installer(db, "Pro Manchester")
    await _post_during_outage(client, fakes)
    fakes.geocoder.unavailable = False

    await asyncio.gather(_recover(fakes), _recover(fakes))

    assert await db.scalar(select(func.count()).select_from(QuoteMatch)) == 1
    assert len(fakes.emails.of("new_lead")) == 1


async def test_a_waiting_request_is_shown_to_the_team_at_once(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    async def waiting() -> int:
        async with SessionFactory() as session:
            return await session.scalar(
                select(func.count()).select_from(QuoteRequest).where(lead_stats.waiting_for_team())
            )

    await create_installer(db, "Pro Manchester")
    await _post_during_outage(client, fakes)
    assert await waiting() == 1  # so the team can choose installers without waiting

    fakes.geocoder.unavailable = False
    await _recover(fakes)
    assert await waiting() == 0  # matched by itself: nothing left for the team


async def test_the_homeowner_sees_nothing_unusual_while_it_waits(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    await create_installer(db, "Pro Manchester")
    fakes.geocoder.unavailable = True
    await client.post("/api/v1/quotes", json=quote_payload())
    confirmation = fakes.emails.of("quote_confirmation")[-1]
    token = parse_qs(urlparse(confirmation.context["link"]).query)["token"][0]
    verified = await client.post("/api/v1/customer/auth/verify", json={"token": token})
    headers = {"Authorization": f"Bearer {verified.json()['session_token']}"}

    overview = await client.get("/api/v1/customer/overview", headers=headers)
    request = overview.json()["requests"][0]

    assert (request["status"], request["status_label"]) == (
        "matching",
        "Active - Matching with installers",
    )
    assert "postcode" not in request["status_detail"].lower()
    assert "lookup" not in request["status_detail"].lower()
