"""The blog: the admin writes and publishes posts; the public sees only live ones."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import Role
from app.models import BlogPost
from app.services import seeding
from tests.helpers import PNG_BYTES, Fakes, auth_headers, create_installer, create_user

BODY = "## Heading\n\n" + "Plenty of useful words about charging an electric car at home. " * 40


def post_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "title": "Choosing a home charger",
        "excerpt": "Everything you need to know before choosing a home EV charger.",
        "body": BODY,
        "category": "Buying Guides",
    }
    return payload | overrides


@pytest.fixture
async def admin(db: AsyncSession) -> dict[str, str]:
    return auth_headers(await create_user(db, role=Role.ADMIN))


async def test_drafts_are_private_until_published(client: httpx.AsyncClient, admin: dict[str, str]):
    created = await client.post("/api/v1/admin/blog/posts", headers=admin, json=post_payload())
    assert created.status_code == 201
    post = created.json()
    assert (post["slug"], post["status"], post["published_at"]) == (
        "choosing-a-home-charger",
        "draft",
        None,
    )
    assert (post["category_slug"], post["author_name"]) == ("buying-guides", "PickASparky Team")
    assert post["reading_minutes"] == 3

    assert (await client.get("/api/v1/blog/posts")).json()["total"] == 0
    assert (await client.get(f"/api/v1/blog/posts/{post['slug']}")).status_code == 404

    published = await client.patch(
        f"/api/v1/admin/blog/posts/{post['id']}", headers=admin, json={"status": "published"}
    )
    assert published.status_code == 200
    assert published.json()["published_at"] is not None

    listing = (await client.get("/api/v1/blog/posts")).json()
    assert listing["total"] == 1
    assert "body" not in listing["items"][0]
    article = (await client.get(f"/api/v1/blog/posts/{post['slug']}")).json()
    assert article["body"] == BODY.strip()
    assert article["title"] == "Choosing a home charger"


async def test_scheduled_posts_appear_once_their_time_comes(
    client: httpx.AsyncClient, db: AsyncSession, admin: dict[str, str]
):
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    created = await client.post(
        "/api/v1/admin/blog/posts",
        headers=admin,
        json=post_payload(status="published", published_at=tomorrow),
    )
    assert created.status_code == 201
    assert (await client.get("/api/v1/blog/posts")).json()["total"] == 0

    post = await db.scalar(select(BlogPost))
    post.published_at = datetime.now(UTC) - timedelta(minutes=1)
    await db.commit()
    assert (await client.get("/api/v1/blog/posts")).json()["total"] == 1


async def test_slugs_are_unique_and_never_reserved(
    client: httpx.AsyncClient, admin: dict[str, str]
):
    first = await client.post("/api/v1/admin/blog/posts", headers=admin, json=post_payload())
    second = await client.post("/api/v1/admin/blog/posts", headers=admin, json=post_payload())
    assert second.json()["slug"] == "choosing-a-home-charger-2"

    taken = await client.post(
        "/api/v1/admin/blog/posts", headers=admin, json=post_payload(slug="choosing-a-home-charger")
    )
    assert taken.status_code == 409
    assert list(taken.json()["error"]["fields"]) == ["slug"]

    renamed = await client.patch(
        f"/api/v1/admin/blog/posts/{second.json()['id']}",
        headers=admin,
        json={"slug": first.json()["slug"]},
    )
    assert renamed.status_code == 409

    for slug in ("page", "Not A Slug", "a"):
        invalid = await client.post(
            "/api/v1/admin/blog/posts", headers=admin, json=post_payload(slug=slug)
        )
        assert invalid.status_code == 422, slug
        assert list(invalid.json()["error"]["fields"]) == ["slug"]


async def test_update_validation_and_derived_fields(
    client: httpx.AsyncClient, admin: dict[str, str]
):
    post = (
        await client.post("/api/v1/admin/blog/posts", headers=admin, json=post_payload())
    ).json()
    url = f"/api/v1/admin/blog/posts/{post['id']}"

    assert (await client.patch(url, headers=admin, json={})).status_code == 422
    cleared = await client.patch(url, headers=admin, json={"title": None})
    assert cleared.status_code == 422
    assert list(cleared.json()["error"]["fields"]) == ["title"]
    bad_image = await client.patch(url, headers=admin, json={"cover_image_url": "javascript:x"})
    assert list(bad_image.json()["error"]["fields"]) == ["cover_image_url"]

    updated = await client.patch(
        url,
        headers=admin,
        json={"category": "Costs & Planning", "body": BODY * 3, "seo_title": "Short title"},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert (body["category_slug"], body["reading_minutes"], body["seo_title"]) == (
        "costs-planning",
        7,
        "Short title",
    )


async def test_listing_category_filter_and_related_posts(
    client: httpx.AsyncClient, admin: dict[str, str]
):
    for title, category in [
        ("Guide one", "Buying Guides"),
        ("Rules one", "Regulations"),
        ("Guide two", "Buying Guides"),
        ("Rules two", "Regulations"),
    ]:
        response = await client.post(
            "/api/v1/admin/blog/posts",
            headers=admin,
            json=post_payload(title=title, category=category, status="published"),
        )
        assert response.status_code == 201

    listing = (await client.get("/api/v1/blog/posts", params={"page_size": 2})).json()
    assert (listing["total"], listing["pages"]) == (4, 2)
    assert [item["title"] for item in listing["items"]] == ["Rules two", "Guide two"]

    guides = (await client.get("/api/v1/blog/posts", params={"category": "buying-guides"})).json()
    assert [item["title"] for item in guides["items"]] == ["Guide two", "Guide one"]

    related = (await client.get("/api/v1/blog/posts/guide-one/related")).json()
    assert [item["title"] for item in related] == ["Guide two", "Rules two", "Rules one"]
    assert (await client.get("/api/v1/blog/posts/no-such-post/related")).status_code == 404


async def test_cover_upload_replace_and_delete(
    client: httpx.AsyncClient, fakes: Fakes, db: AsyncSession, admin: dict[str, str]
):
    post = (
        await client.post("/api/v1/admin/blog/posts", headers=admin, json=post_payload())
    ).json()
    url = f"/api/v1/admin/blog/posts/{post['id']}"
    files = {"file": ("cover.png", PNG_BYTES, "image/png")}

    first = await client.post(f"{url}/cover", headers=admin, files=files)
    assert first.status_code == 200
    assert first.json()["cover_image_url"] == "https://images.test/blog/image-1.png"
    assert first.json()["cover_image_alt"] == "Choosing a home charger"

    second = await client.post(f"{url}/cover", headers=admin, files=files, data={"alt": "A car"})
    assert second.json()["cover_image_alt"] == "A car"
    assert fakes.storage.deleted == ["blog/image-1"]

    not_an_image = await client.post(
        f"{url}/cover", headers=admin, files={"file": ("x.txt", b"hello", "text/plain")}
    )
    assert not_an_image.status_code == 415

    assert (await client.delete(url, headers=admin)).status_code == 204
    assert fakes.storage.deleted == ["blog/image-1", "blog/image-2"]
    assert await db.scalar(select(func.count()).select_from(BlogPost)) == 0


async def test_only_admins_manage_the_blog(client: httpx.AsyncClient, db: AsyncSession):
    installer = await create_installer(db, "Pro Manchester")
    assert (await client.get("/api/v1/admin/blog/posts")).status_code == 401
    forbidden = await client.post(
        "/api/v1/admin/blog/posts", headers=auth_headers(installer.user), json=post_payload()
    )
    assert forbidden.status_code == 403


async def test_sample_posts_seed_once_and_purge_without_touching_admin_posts(
    client: httpx.AsyncClient, db: AsyncSession, admin: dict[str, str]
):
    await client.post(
        "/api/v1/admin/blog/posts", headers=admin, json=post_payload(status="published")
    )
    assert await seeding.seed_blog(db) == 6
    assert await seeding.seed_blog(db) == 0

    listing = (await client.get("/api/v1/blog/posts", params={"page_size": 20})).json()
    assert listing["total"] == 7
    featured = [item for item in listing["items"] if item["is_featured"]]
    assert len(featured) == 1
    assert all(item["cover_image_url"] for item in listing["items"][1:])

    assert await seeding.purge_blog(db) == 6
    remaining = (await client.get("/api/v1/blog/posts")).json()["items"]
    assert [item["slug"] for item in remaining] == ["choosing-a-home-charger"]


async def test_start_up_seeding_only_fills_an_empty_blog(
    client: httpx.AsyncClient, db: AsyncSession, admin: dict[str, str]
):
    assert await seeding.seed_blog(db, only_if_empty=True) == 6
    assert await seeding.purge_blog(db) == 6

    await client.post("/api/v1/admin/blog/posts", headers=admin, json=post_payload())
    # A draft is enough: the admin has started on the blog, so no samples come back.
    assert await seeding.seed_blog(db, only_if_empty=True) == 0
    assert (await client.get("/api/v1/blog/posts")).json()["total"] == 0
