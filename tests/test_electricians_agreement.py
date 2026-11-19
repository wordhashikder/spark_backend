"""The Electricians Agreement page: an editable legal document that starts empty."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import DOCUMENTS
from app.core.enums import Role, StaffRole
from tests.helpers import Fakes, auth_headers, create_user

ADMIN = "/api/v1/admin"
KEY = "electricians-agreement"


async def _owner(db: AsyncSession) -> dict[str, str]:
    return auth_headers(await create_user(db, role=Role.ADMIN, staff_role=StaffRole.OWNER))


async def test_the_agreement_starts_empty_and_is_listed_with_the_legal_pages(
    client: httpx.AsyncClient, db: AsyncSession
):
    headers = await _owner(db)
    listed = {
        item["key"]: item for item in (await client.get(f"{ADMIN}/content", headers=headers)).json()
    }
    assert listed[KEY]["group"] == "Legal"
    assert listed[KEY]["path"] == "/electricians-agreement/"
    assert listed[KEY]["customised"] is False

    public = (await client.get(f"/api/v1/content/{KEY}")).json()["content"]
    assert public["header"]["title"] == "Electricians Agreement"
    assert public["body"]["sections"] == []
    # The other legal pages are untouched and still need at least one section.
    assert DOCUMENTS["terms"].defaults()["body"]["sections"]
    assert DOCUMENTS["privacy"].defaults()["body"]["sections"]


async def test_the_team_can_write_the_agreement_and_the_website_is_refreshed(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    headers = await _owner(db)
    fakes.revalidator.tags.clear()

    # Saving it before anything is written is allowed; the page just stays empty.
    empty = DOCUMENTS[KEY].defaults()
    assert (
        await client.put(f"{ADMIN}/content/{KEY}", headers=headers, json={"content": empty})
    ).status_code == 200

    written = DOCUMENTS[KEY].defaults()
    written["body"]["sections"] = [
        {"title": "Who this agreement is with", "body": "Paragraph one.\n\n- A bullet"},
        {"title": "Your responsibilities", "body": "Hold the **required** accreditations."},
    ]
    saved = await client.put(f"{ADMIN}/content/{KEY}", headers=headers, json={"content": written})
    assert saved.status_code == 200, saved.text
    assert f"content:{KEY}" in fakes.revalidator.tags

    sections = (await client.get(f"/api/v1/content/{KEY}")).json()["content"]["body"]["sections"]
    assert [section["title"] for section in sections] == [
        "Who this agreement is with",
        "Your responsibilities",
    ]

    # Removing every section again is fine too, and it can be reset to the original wording.
    written["body"]["sections"] = []
    assert (
        await client.put(f"{ADMIN}/content/{KEY}", headers=headers, json={"content": written})
    ).status_code == 200
    reset = await client.delete(f"{ADMIN}/content/{KEY}", headers=headers)
    assert reset.status_code == 200


async def test_only_content_editors_can_change_the_agreement(
    client: httpx.AsyncClient, db: AsyncSession
):
    support = auth_headers(await create_user(db, role=Role.ADMIN, staff_role=StaffRole.SUPPORT))
    body = {"content": DOCUMENTS[KEY].defaults()}
    assert (
        await client.put(f"{ADMIN}/content/{KEY}", headers=support, json=body)
    ).status_code == 403
    assert (await client.put(f"{ADMIN}/content/{KEY}", json=body)).status_code == 401
