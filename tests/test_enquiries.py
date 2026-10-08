"""Direct enquiries: the "Request a Quote" form on an installer's profile."""

from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.enums import InstallerStatus, Plan, Role
from app.models import InstallerEnquiry
from tests.helpers import Fakes, auth_headers, create_installer, create_user


def enquiry_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "name": "Sam Taylor",
        "email": "Sam@Example.com",
        "phone": "07700 900123",
        "message": "Could you quote for a tethered charger on the front of the house?",
    }
    return payload | overrides


async def test_enquiry_goes_to_the_installer_and_the_customer_gets_a_copy(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_installer(db, "Pro Manchester")

    response = await client.post(
        f"/api/v1/installers/{installer.slug}/enquiries", json=enquiry_payload()
    )
    assert response.status_code == 202
    assert response.json() == {"message": "Your request has been sent. We've emailed you a copy."}

    enquiry = await db.scalar(select(InstallerEnquiry))
    assert (enquiry.installer_id, enquiry.name, enquiry.email, enquiry.phone) == (
        installer.id,
        "Sam Taylor",
        "sam@example.com",
        "07700 900123",
    )
    assert enquiry.ip_hash == security.hash_ip("127.0.0.1")
    assert enquiry.sent_to_installer is True

    notification, acknowledgement = fakes.emails.sent
    assert (notification.template, notification.to) == (
        "installer_enquiry",
        "pro-manchester@example.com",
    )
    assert notification.reply_to == "sam@example.com"
    assert notification.context["message"] == enquiry.message
    assert (acknowledgement.template, acknowledgement.to) == ("enquiry_ack", "sam@example.com")
    assert acknowledgement.context["profile_url"] == (
        "https://frontend.test/uk/installer/pro-manchester/"
    )
    assert acknowledgement.subject == "Your quote request has been sent to Pro Manchester"


async def test_phone_number_is_optional_but_must_be_valid_when_given(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_installer(db, "Pro Manchester")
    url = f"/api/v1/installers/{installer.slug}/enquiries"

    assert (await client.post(url, json=enquiry_payload(phone=""))).status_code == 202
    assert await db.scalar(select(InstallerEnquiry.phone)) is None
    rendered = fakes.emails._renderer.render(fakes.emails.of("installer_enquiry")[0])
    assert "No phone number given" in rendered.get_body(preferencelist=("plain",)).get_content()

    invalid = await client.post(
        url, json=enquiry_payload(phone="call me", message="short", name="S", email="sam@")
    )
    assert invalid.status_code == 422
    assert set(invalid.json()["error"]["fields"]) == {"phone", "message", "name", "email"}


async def test_free_plan_requests_go_to_the_team_not_the_installer(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    free = await create_installer(db, "Free Manchester", plan=Plan.FREE)

    response = await client.post(
        f"/api/v1/installers/{free.slug}/enquiries", json=enquiry_payload(phone="")
    )
    assert response.status_code == 202
    assert response.json() == {"message": "Your request has been sent. We've emailed you a copy."}

    enquiry = await db.scalar(select(InstallerEnquiry))
    assert (enquiry.installer_id, enquiry.sent_to_installer) == (free.id, False)

    notification, acknowledgement = fakes.emails.sent
    assert (notification.template, notification.to) == (
        "enquiry_for_team",
        "support@pickasparky.test",
    )
    assert notification.reply_to == "sam@example.com"
    assert notification.context["installer_email"] == "free-manchester@example.com"
    team_copy = fakes.emails._renderer.render(notification)
    assert "Free plan" in team_copy.get_body(preferencelist=("plain",)).get_content()

    assert (acknowledgement.template, acknowledgement.to) == ("enquiry_ack", "sam@example.com")
    assert acknowledgement.subject == "We've received your quote request for Free Manchester"
    customer_copy = fakes.emails._renderer.render(acknowledgement)
    text = customer_copy.get_body(preferencelist=("plain",)).get_content()
    assert "The PickASparky team will get back to you" in text

    # The installer never sees it in their own list.
    listed = await client.get("/api/v1/installers/me/enquiries", headers=auth_headers(free.user))
    assert listed.json()["total"] == 0


async def test_unlisted_installers_cannot_be_contacted(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    pending = await create_installer(db, "Pending Manchester", status=InstallerStatus.PENDING)

    for slug in (pending.slug, "no-such-installer"):
        missing = await client.post(f"/api/v1/installers/{slug}/enquiries", json=enquiry_payload())
        assert missing.status_code == 404

    assert await db.scalar(select(func.count()).select_from(InstallerEnquiry)) == 0
    assert fakes.emails.sent == []


async def test_honeypot_enquiries_look_sent_but_store_nothing(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession
):
    installer = await create_installer(db, "Pro Manchester")
    response = await client.post(
        f"/api/v1/installers/{installer.slug}/enquiries",
        json=enquiry_payload(website="https://spam.example"),
    )
    assert response.status_code == 202
    assert await db.scalar(select(func.count()).select_from(InstallerEnquiry)) == 0
    assert fakes.emails.sent == []


async def test_installer_and_admin_can_list_enquiries(client: httpx.AsyncClient, db: AsyncSession):
    mine = await create_installer(db, "Pro Manchester")
    other = await create_installer(db, "Pro Salford", location="salford")
    for installer in (mine, other, mine):
        await client.post(f"/api/v1/installers/{installer.slug}/enquiries", json=enquiry_payload())

    own = await client.get("/api/v1/installers/me/enquiries", headers=auth_headers(mine.user))
    assert own.status_code == 200
    assert own.json()["total"] == 2
    assert set(own.json()["items"][0]) == {
        "id",
        "name",
        "email",
        "phone",
        "message",
        "created_at",
    }

    admin = auth_headers(await create_user(db, role=Role.ADMIN))
    everything = (await client.get("/api/v1/admin/enquiries", headers=admin)).json()
    assert everything["total"] == 3
    assert {item["installer_name"] for item in everything["items"]} == {
        "Pro Manchester",
        "Pro Salford",
    }
    assert all(item["sent_to_installer"] for item in everything["items"])
    forbidden = await client.get("/api/v1/admin/enquiries", headers=auth_headers(mine.user))
    assert forbidden.status_code == 403
