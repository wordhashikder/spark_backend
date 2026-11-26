"""Website pages (Dashboard > Pages) and accreditation schemes (Dashboard > Accreditations)."""

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Role, StaffRole
from app.models import AccreditationScheme, SitePage
from app.services import seeding
from tests.helpers import auth_headers, create_installer, create_user

ADMIN = "/api/v1/admin"
API = "/api/v1"
SECTION = {"heading": "What it costs", "body": "Most installs cost **£800 to £1,200**."}


@pytest.fixture
async def headers(db: AsyncSession) -> dict[str, str]:
    user = await create_user(db, role=Role.ADMIN, staff_role=StaffRole.OWNER)
    return auth_headers(user)


async def _create(client: httpx.AsyncClient, headers: dict[str, str], **fields) -> dict:
    body = {"title": "Cost guide", "path": "/uk/home-ev-charger-installation/cost/", **fields}
    response = await client.post(f"{ADMIN}/pages", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _lookup(client: httpx.AsyncClient, path: str, preview: str | None = None):
    params = {"path": path, **({"preview": preview} if preview else {})}
    return await client.get(f"{API}/pages/lookup", params=params)


# ---- Pages --------------------------------------------------------------------------------


async def test_new_page_is_hidden_until_it_has_content_and_is_published(
    client: httpx.AsyncClient, headers: dict[str, str]
):
    page = await _create(client, headers, is_published=True)
    assert page["has_content"] is False
    assert page["is_indexable"] is False

    # An empty page still opens (title and intro only) but is kept away from Google.
    shown = (await _lookup(client, page["path"])).json()["page"]
    assert shown["title"] == "Cost guide"
    assert shown["indexable"] is False
    assert (await client.get(f"{API}/pages/sitemap")).json() == []

    updated = await client.patch(
        f"{ADMIN}/pages/{page['id']}", json={"sections": [SECTION]}, headers=headers
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["is_indexable"] is True
    shown = (await _lookup(client, page["path"])).json()["page"]
    assert shown["indexable"] is True
    sitemap = (await client.get(f"{API}/pages/sitemap")).json()
    assert [entry["path"] for entry in sitemap] == [page["path"]]


async def test_unpublished_page_is_only_visible_through_a_preview_link(
    client: httpx.AsyncClient, headers: dict[str, str]
):
    page = await _create(client, headers)
    await client.patch(f"{ADMIN}/pages/{page['id']}", json={"sections": [SECTION]}, headers=headers)

    assert (await _lookup(client, page["path"])).status_code == 404
    assert (await client.get(f"{API}/pages/sitemap")).json() == []

    token = (await client.post(f"{ADMIN}/pages/{page['id']}/preview", headers=headers)).json()
    assert token["expires_in"] > 0
    previewed = (await _lookup(client, page["path"], token["token"])).json()["page"]
    assert previewed["preview"] is True
    assert previewed["indexable"] is False

    assert (await _lookup(client, page["path"], "not-a-token")).status_code == 404


async def test_changing_a_pages_address_keeps_the_old_one_working(
    client: httpx.AsyncClient, headers: dict[str, str]
):
    page = await _create(client, headers, is_published=True)
    moved = await client.patch(
        f"{ADMIN}/pages/{page['id']}",
        json={"path": "/uk/home-ev-charger-installation/prices/"},
        headers=headers,
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["previous_paths"] == [page["path"]]

    redirect = (await _lookup(client, page["path"])).json()
    assert redirect == {"page": None, "redirect_to": "/uk/home-ev-charger-installation/prices/"}


async def test_addresses_are_checked(client: httpx.AsyncClient, headers: dict[str, str]):
    await _create(client, headers)
    for path in (
        "/uk/home-ev-charger-installation/cost/",  # taken
        "/blog/my-post/",  # belongs to the blog
        "/uk/ev-charger-installers/manchester/",  # belongs to the directory
        "/uk/accreditations/",  # the overview page
        "/api/anything/",  # the API
        "/uk/with space/",  # not a web-safe address
        "/",
    ):
        response = await client.post(
            f"{ADMIN}/pages", json={"title": "Clash", "path": path}, headers=headers
        )
        assert response.status_code in (409, 422), (path, response.text)


async def test_images_and_links_in_the_text_are_restricted(
    client: httpx.AsyncClient, headers: dict[str, str]
):
    page = await _create(client, headers)
    url = f"{ADMIN}/pages/{page['id']}"
    cloudinary = "https://res.cloudinary.com/demo/image/upload/x.jpg"

    ok = {"heading": "Photos", "body": f"![A charger]({cloudinary})\n\n[Quote](/get-quotes/)"}
    assert (await client.patch(url, json={"sections": [ok]}, headers=headers)).status_code == 200

    for body in (
        "![x](https://evil.example/a.png)",
        "[click](javascript:alert(1))",
        "[![x](https://evil.example/a.png)](/get-quotes/)",
    ):
        bad = {"heading": "Bad", "body": body}
        response = await client.patch(url, json={"sections": [bad]}, headers=headers)
        assert response.status_code == 422, (body, response.text)

    no_alt = {**SECTION, "image_url": cloudinary}
    response = await client.patch(url, json={"sections": [no_alt]}, headers=headers)
    assert response.status_code == 422


async def test_supporting_pages_link_back_to_their_main_page(
    client: httpx.AsyncClient, headers: dict[str, str]
):
    main = await _create(
        client, headers, title="Home EV charger installation", path="/uk/home-ev-charger/"
    )
    child = await _create(
        client,
        headers,
        title="Cost",
        path="/uk/home-ev-charger/cost/",
        parent_path=main["path"],
        is_published=True,
    )
    await client.patch(
        f"{ADMIN}/pages/{child['id']}", json={"sections": [SECTION]}, headers=headers
    )
    await client.patch(f"{ADMIN}/pages/{main['id']}", json={"is_published": True}, headers=headers)

    shown = (await _lookup(client, child["path"])).json()["page"]
    assert shown["parent"] == {"path": main["path"], "title": main["title"]}
    parent = (await _lookup(client, main["path"])).json()["page"]
    assert [card["path"] for card in parent["children"]] == [child["path"]]

    # A main page with supporting pages cannot be deleted from under them.
    blocked = await client.delete(f"{ADMIN}/pages/{main['id']}", headers=headers)
    assert blocked.status_code == 409
    assert (await client.delete(f"{ADMIN}/pages/{child['id']}", headers=headers)).status_code == 204


async def test_seeded_pages_are_four_main_pages_and_one_sample(db: AsyncSession):
    await seeding.insert_pages(db)
    await db.commit()
    again = await seeding.insert_pages(db)
    assert again == 0

    rows = {page.path: page for page in await db.scalars(select(SitePage))}
    for path in (
        "/uk/home-ev-charger-installation/",
        "/uk/ev-charger-replacement/",
        "/uk/commercial-ev-charging/",
        "/uk/workplace-ev-charging/",
    ):
        assert rows[path].is_published
        assert not rows[path].has_content
        assert not rows[path].is_indexable
    sample = rows["/uk/home-ev-charger-installation/cost/"]
    assert sample.is_published is False
    assert sample.parent_path == "/uk/home-ev-charger-installation/"


async def test_pages_need_the_content_permission(db: AsyncSession, client: httpx.AsyncClient):
    support = await create_user(db, role=Role.ADMIN, staff_role=StaffRole.SUPPORT)
    response = await client.get(f"{ADMIN}/pages", headers=auth_headers(support))
    assert response.status_code == 403
    assert (await client.get(f"{ADMIN}/pages")).status_code == 401


# ---- Accreditation schemes ----------------------------------------------------------------


async def test_schemes_start_with_the_seven_known_ones(client: httpx.AsyncClient):
    schemes = (await client.get(f"{API}/accreditation-schemes")).json()
    assert [item["key"] for item in schemes] == [
        "niceic",
        "napit",
        "trustmark",
        "elecsa",
        "ozev",
        "mcs",
        "select",
    ]
    niceic = schemes[0]
    assert niceic["badge"] == "Recognised Standard"
    assert niceic["card_title"] == "NICEIC Approved"
    assert niceic["href"] is None  # its page has no content yet


async def test_a_scheme_gets_its_own_page_and_the_link_appears_with_content(
    client: httpx.AsyncClient, db: AsyncSession, headers: dict[str, str]
):
    await seeding.insert_pages(db)
    await db.commit()
    page = await db.scalar(select(SitePage).where(SitePage.scheme_key == "niceic"))
    assert page is not None
    assert page.path == "/uk/accreditations/niceic/"
    assert page.parent_path == "/uk/accreditations/"

    await client.patch(f"{ADMIN}/pages/{page.id}", json={"sections": [SECTION]}, headers=headers)
    schemes = {
        item["key"]: item for item in (await client.get(f"{API}/accreditation-schemes")).json()
    }
    assert schemes["niceic"]["href"] == "/uk/accreditations/niceic/"
    assert schemes["napit"]["href"] is None

    # The page of a scheme cannot be removed on its own.
    deleted = await client.delete(f"{ADMIN}/pages/{page.id}", headers=headers)
    assert deleted.status_code == 409


async def test_saving_a_scheme_page_refreshes_the_schemes_on_the_website(
    client: httpx.AsyncClient, db: AsyncSession, headers: dict[str, str], fakes
):
    """The card on installer profiles links to the page; its cache must not wait an hour."""
    await seeding.insert_pages(db)
    await db.commit()
    scheme_page = await db.scalar(select(SitePage).where(SitePage.scheme_key == "niceic"))
    other = await _create(client, headers, path="/uk/another-page/")
    assert scheme_page is not None

    fakes.revalidator.tags.clear()
    await client.patch(
        f"{ADMIN}/pages/{other['id']}", json={"sections": [SECTION]}, headers=headers
    )
    assert fakes.revalidator.tags == ["pages"]

    fakes.revalidator.tags.clear()
    await client.patch(
        f"{ADMIN}/pages/{scheme_page.id}", json={"sections": [SECTION]}, headers=headers
    )
    assert fakes.revalidator.tags == ["pages", "accreditation-schemes"]


async def test_team_adds_edits_and_removes_a_scheme(
    client: httpx.AsyncClient, db: AsyncSession, headers: dict[str, str]
):
    created = await client.post(
        f"{ADMIN}/accreditation-schemes",
        json={
            "name": "Gas Safe",
            "badge": "Gas Register",
            "card_title": "Gas Safe Registered",
            "card_text": "Registered with the Gas Safe Register for gas work.",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    scheme = created.json()
    assert scheme["key"] == "gas-safe"
    assert scheme["page_path"] == "/uk/accreditations/gas-safe/"

    edited = await client.patch(
        f"{ADMIN}/accreditation-schemes/gas-safe", json={"badge": None}, headers=headers
    )
    assert edited.json()["badge"] is None

    hidden = await client.patch(
        f"{ADMIN}/accreditation-schemes/gas-safe", json={"is_active": False}, headers=headers
    )
    assert hidden.json()["is_active"] is False

    deleted = await client.delete(f"{ADMIN}/accreditation-schemes/gas-safe", headers=headers)
    assert deleted.status_code == 204
    assert (
        await db.scalar(select(AccreditationScheme).where(AccreditationScheme.key == "gas-safe"))
        is None
    )
    assert await db.scalar(select(SitePage).where(SitePage.scheme_key == "gas-safe")) is None


async def test_a_scheme_in_use_cannot_be_deleted_and_inactive_ones_are_not_offered(
    client: httpx.AsyncClient, db: AsyncSession, headers: dict[str, str]
):
    await create_installer(db, "Certified Sparks", accreditations=("niceic",))

    in_use = await client.delete(f"{ADMIN}/accreditation-schemes/niceic", headers=headers)
    assert in_use.status_code == 409

    await client.patch(
        f"{ADMIN}/accreditation-schemes/napit", json={"is_active": False}, headers=headers
    )
    installer = await create_user(db, role=Role.INSTALLER)
    del installer  # a fresh installer account is not needed: the listing form is checked below
    created = await client.post(
        f"{ADMIN}/installers",
        json={
            "business_name": "New Sparks",
            "contact_email": "new@example.com",
            "phone": "07123456789",
            "base_postcode": "M1 1AE",
            "accreditations": ["napit"],
        },
        headers=headers,
    )
    assert created.status_code == 422, created.text