"""Create, read, update and delete from the Dashboard: installers, reviews and towns, plus the
optional closing section on website pages."""

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content import DOCUMENTS
from app.core.enums import ReviewStatus, Role, StaffRole, SubscriptionStatus
from app.models import Installer, Location, Review, User
from tests.helpers import (
    PNG_BYTES,
    Fakes,
    Plan,
    auth_headers,
    create_installer,
    create_review,
    create_user,
)

ADMIN = "/api/v1/admin"


async def _owner(db: AsyncSession) -> dict[str, str]:
    user = await create_user(db, role=Role.ADMIN, staff_role=StaffRole.OWNER)
    return auth_headers(user)


async def test_admin_area_edit_shows_on_the_public_page_for_every_plan(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    """The team's edit of "Areas covered" reaches the public profile, even on the Free plan."""
    headers = await _owner(db)
    installer = await create_installer(db, "Areas Free Ltd", plan=Plan.FREE)
    fakes.revalidator.tags.clear()

    response = await client.patch(
        f"{ADMIN}/installers/{installer.id}",
        headers=headers,
        json={"areas_covered": ["Rochdale", "Oldham", "Bury"]},
    )
    assert response.status_code == 200, response.text

    public = (await client.get("/api/v1/installers/areas-free-ltd")).json()
    assert public["areas_covered"] == ["Rochdale", "Oldham", "Bury"]
    # The website is told to refresh this listing's cached pages at once.
    assert "installers" in fakes.revalidator.tags


async def test_edit_every_installer_field_logo_and_photos(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    headers = await _owner(db)
    installer = await create_installer(db, "Full Edit Ltd")
    url = f"{ADMIN}/installers/{installer.id}"

    response = await client.patch(
        url,
        headers=headers,
        json={
            "tagline": "Fitted right",
            "website_url": "https://fulledit.example.com",
            "company_number": "12345678",
            "years_experience": 7,
            "services": ["ev_charger_installation"],
            "areas_covered": ["Altrincham", "Sale"],
            "accreditations": [{"scheme": "ozev", "registration_number": "OZ-1"}],
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["tagline"] == "Fitted right"
    assert data["years_experience"] == 7
    assert data["services"] == ["ev_charger_installation"]
    assert data["areas_covered"] == ["Altrincham", "Sale"]
    assert [item["scheme"] for item in data["accreditations"]] == ["ozev"]

    cleared = await client.patch(url, headers=headers, json={"tagline": "", "website_url": None})
    assert cleared.json()["tagline"] is None
    empty = await client.patch(url, headers=headers, json={"services": []})
    assert empty.status_code == 422

    logo = await client.post(
        f"{url}/logo", headers=headers, files={"file": ("l.png", PNG_BYTES, "image/png")}
    )
    assert logo.status_code == 200, logo.text
    assert logo.json()["logo_url"].startswith("https://images.test/")
    photo = await client.post(
        f"{url}/photos",
        headers=headers,
        files={"file": ("p.png", PNG_BYTES, "image/png")},
        data={"alt": "A tidy install"},
    )
    assert photo.status_code == 201, photo.text
    photos = photo.json()["photos"]
    assert [item["alt"] for item in photos] == ["A tidy install"]
    gone = await client.delete(f"{url}/photos/{photos[0]['id']}", headers=headers)
    assert gone.json()["photos"] == []
    assert (await client.delete(f"{url}/logo", headers=headers)).json()["logo_url"] is None


async def test_delete_installer_removes_listing_account_and_reviews(
    client: httpx.AsyncClient, db: AsyncSession
):
    headers = await _owner(db)
    installer = await create_installer(db, "Delete Me Ltd")
    await create_review(db, installer)
    user_id, installer_id = installer.user_id, installer.id

    response = await client.delete(f"{ADMIN}/installers/{installer_id}", headers=headers)
    assert response.status_code == 204, response.text
    db.expire_all()
    assert await db.get(Installer, installer_id) is None
    assert await db.get(User, user_id) is None
    assert (await db.scalars(select(Review))).first() is None
    assert (
        await client.get(f"{ADMIN}/installers/{installer_id}", headers=headers)
    ).status_code == 404


async def test_delete_installer_with_live_subscription_is_refused(
    client: httpx.AsyncClient, db: AsyncSession
):
    headers = await _owner(db)
    installer = await create_installer(db, "Paying Ltd")
    installer.subscription_status = SubscriptionStatus.ACTIVE
    await db.commit()
    response = await client.delete(f"{ADMIN}/installers/{installer.id}", headers=headers)
    assert response.status_code == 409
    assert "subscription" in response.text


async def test_review_create_edit_move_and_delete_keep_ratings_right(
    client: httpx.AsyncClient, db: AsyncSession
):
    headers = await _owner(db)
    first = await create_installer(db, "First Sparky")
    second = await create_installer(db, "Second Sparky")

    created = await client.post(
        f"{ADMIN}/reviews",
        headers=headers,
        json={
            "installer_id": str(first.id),
            "rating": 5,
            "title": "Brilliant job",
            "body": "Turned up on time and left everything spotless.",
            "author_name": "Sam Jones",
            "author_location": "Stockport",
        },
    )
    assert created.status_code == 201, created.text
    review = created.json()
    assert review["status"] == "published"
    assert review["verified"] is False
    await db.refresh(first)
    assert (first.review_count, float(first.rating_avg)) == (1, 5.0)

    edited = await client.patch(
        f"{ADMIN}/reviews/{review['id']}", headers=headers, json={"rating": 3, "title": "Fine job"}
    )
    assert edited.status_code == 200, edited.text
    assert (edited.json()["rating"], edited.json()["title"]) == (3, "Fine job")
    await db.refresh(first)
    assert float(first.rating_avg) == 3.0

    moved = await client.patch(
        f"{ADMIN}/reviews/{review['id']}", headers=headers, json={"installer_id": str(second.id)}
    )
    assert moved.json()["installer_slug"] == second.slug
    await db.refresh(first)
    await db.refresh(second)
    assert (first.review_count, second.review_count) == (0, 1)

    bad = await client.patch(f"{ADMIN}/reviews/{review['id']}", headers=headers, json={"rating": 9})
    assert bad.status_code == 422

    assert (
        await client.delete(f"{ADMIN}/reviews/{review['id']}", headers=headers)
    ).status_code == 204
    await db.refresh(second)
    assert (second.review_count, second.rating_avg) == (0, None)
    assert (
        await client.delete(f"{ADMIN}/reviews/{review['id']}", headers=headers)
    ).status_code == 404


async def test_pending_review_created_by_team_stays_hidden(
    client: httpx.AsyncClient, db: AsyncSession
):
    headers = await _owner(db)
    installer = await create_installer(db, "Hidden Review Ltd")
    response = await client.post(
        f"{ADMIN}/reviews",
        headers=headers,
        json={
            "installer_id": str(installer.id),
            "rating": 4,
            "title": "Draft review",
            "body": "Waiting to be approved by the team.",
            "author_name": "Pat",
            "status": "pending",
        },
    )
    assert response.status_code == 201
    await db.refresh(installer)
    assert installer.review_count == 0
    review = await db.scalar(select(Review))
    assert review is not None
    assert review.status is ReviewStatus.PENDING


async def test_location_delete_rules(client: httpx.AsyncClient, db: AsyncSession):
    headers = await _owner(db)
    created = await client.post(
        f"{ADMIN}/locations",
        headers=headers,
        json={"name": "Testville", "postcode": "LS1 4AP"},
    )
    assert created.status_code == 201, created.text
    slug = created.json()["slug"]

    await client.patch(f"{ADMIN}/locations/{slug}", headers=headers, json={"is_published": True})
    live = await client.delete(f"{ADMIN}/locations/{slug}", headers=headers)
    assert live.status_code == 409

    await client.patch(f"{ADMIN}/locations/{slug}", headers=headers, json={"is_published": False})
    # A town with installers cannot go.
    manchester = await db.scalar(select(Location).where(Location.slug == "manchester"))
    assert manchester is not None
    await create_installer(db, "Anchor Ltd")
    manchester_slug = manchester.slug
    await client.patch(
        f"{ADMIN}/locations/{manchester_slug}", headers=headers, json={"is_published": False}
    )
    blocked = await client.delete(f"{ADMIN}/locations/{manchester_slug}", headers=headers)
    assert blocked.status_code == 409
    await client.patch(
        f"{ADMIN}/locations/{manchester_slug}", headers=headers, json={"is_published": True}
    )

    assert (await client.delete(f"{ADMIN}/locations/{slug}", headers=headers)).status_code == 204
    assert (await client.delete(f"{ADMIN}/locations/{slug}", headers=headers)).status_code == 404


async def test_location_closing_section_is_editable_and_public(
    client: httpx.AsyncClient, db: AsyncSession
):
    headers = await _owner(db)
    response = await client.patch(
        f"{ADMIN}/locations/manchester",
        headers=headers,
        json={"extra_title": "Why Manchester", "extra_body": "A **great** place."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["extra_title"] == "Why Manchester"
    public = (await client.get("/api/v1/locations/manchester")).json()
    assert public["extra_body"] == "A **great** place."
    cleared = await client.patch(
        f"{ADMIN}/locations/manchester", headers=headers, json={"extra_title": "", "extra_body": ""}
    )
    assert cleared.json()["extra_title"] is None


async def test_pages_have_an_empty_closing_section_by_default(
    client: httpx.AsyncClient, db: AsyncSession
):
    for key in ("home", "installers-hub", "location", "about", "faq", "blog", "safety"):
        defaults = DOCUMENTS[key].defaults()
        assert defaults["closing"]["title"] == defaults["closing"]["body"] == ""
    assert "closing" not in DOCUMENTS["privacy"].defaults()

    headers = await _owner(db)
    saved = DOCUMENTS["home"].defaults()
    saved["closing"].update(
        title="Our promise",
        body="## Heading\n\nSome **text**.",
        button_label="Get quotes",
        button_link="/get-quotes/",
    )
    response = await client.put(f"{ADMIN}/content/home", headers=headers, json={"content": saved})
    assert response.status_code == 200, response.text
    public = (await client.get("/api/v1/content/home")).json()
    assert public["content"]["closing"]["title"] == "Our promise"

    saved["closing"]["button_link"] = "javascript:alert(1)"
    refused = await client.put(f"{ADMIN}/content/home", headers=headers, json={"content": saved})
    assert refused.status_code == 422


async def test_new_crud_routes_need_the_right_staff_role(
    client: httpx.AsyncClient, db: AsyncSession
):
    support = await create_user(db, role=Role.ADMIN, staff_role=StaffRole.SUPPORT)
    headers = auth_headers(support)
    installer = await create_installer(db, "Guarded Ltd")
    for method, path in (
        ("DELETE", f"{ADMIN}/installers/{installer.id}"),
        ("POST", f"{ADMIN}/reviews"),
        ("DELETE", f"{ADMIN}/locations/nowhere"),
    ):
        response = await client.request(method, path, headers=headers, json={})
        assert response.status_code in (401, 403), (method, path, response.status_code)
    anonymous = await client.delete(f"{ADMIN}/reviews/{installer.id}")
    assert anonymous.status_code in (401, 403)
