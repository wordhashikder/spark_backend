"""The back office: overview, roles and access, team, settings, website content, locations,
listings, held requests and the team writing into conversations."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import QuoteStatus, Role, StaffRole
from app.models import Installer, Location, QuoteMatch, QuoteRequest, User
from app.services.revalidation import HttpRevalidator
from tests.helpers import (
    PASSWORD,
    STOCKPORT,
    Fakes,
    Plan,
    auth_headers,
    create_installer,
    create_user,
    quote_payload,
)

ADMIN = "/api/v1/admin"


async def _staff(db: AsyncSession, role: StaffRole = StaffRole.OWNER, email: str | None = None):
    user = await create_user(db, role=Role.ADMIN, staff_role=role, email=email)
    return user, auth_headers(user)


# ---- Overview, nav and search -------------------------------------------------------------


async def test_overview_kpis_chart_areas_and_recent_leads(
    client: httpx.AsyncClient, db: AsyncSession
):
    _, headers = await _staff(db)
    await create_installer(db, "Counted Installer")
    for _ in range(2):
        await client.post("/api/v1/quotes", json=quote_payload())

    response = await client.get(f"{ADMIN}/overview", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["leads"]["value"] == 2
    assert data["active_installers"]["value"] == 1
    assert data["match_rate"]["value"] == 100.0
    assert "installers told per lead" in data["match_rate"]["hint"]
    assert len(data["monthly"]) == 6
    assert data["monthly"][-1]["leads"] == 2
    assert data["leads_by_area"] == [{"key": "Manchester", "count": 2}]
    recent = data["recent_leads"]
    assert len(recent) == 2
    assert recent[0]["installers_matched"] == 1
    assert recent[0]["stage"] == "open"

    nav = (await client.get(f"{ADMIN}/nav", headers=headers)).json()
    assert nav == {"leads": 0, "installers": 0, "reviews": 0, "inbox": 0}

    found = (await client.get(f"{ADMIN}/search", params={"q": "count"}, headers=headers)).json()
    assert [hit["kind"] for hit in found["hits"]] == ["installer"]
    assert found["hits"][0]["href"].startswith("/installers?open=")
    by_postcode = (await client.get(f"{ADMIN}/search", params={"q": "M1"}, headers=headers)).json()
    assert {hit["kind"] for hit in by_postcode["hits"]} >= {"lead"}


# ---- Roles and access ---------------------------------------------------------------------


async def test_staff_roles_limit_modules_and_owners_edit_the_matrix(
    client: httpx.AsyncClient, db: AsyncSession
):
    _, owner = await _staff(db)
    editor_user, editor = await _staff(db, StaffRole.EDITOR)
    installer = await create_installer(db, "Not Staff")

    assert (await client.get(f"{ADMIN}/content", headers=editor)).status_code == 200
    denied = await client.get(f"{ADMIN}/quotes", headers=editor)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "module_forbidden"
    assert (await client.get(f"{ADMIN}/team", headers=editor)).status_code == 403
    assert (
        await client.get(f"{ADMIN}/overview", headers=auth_headers(installer.user))
    ).status_code == 403

    # The editor's search and badges only cover their modules.
    nav = (await client.get(f"{ADMIN}/nav", headers=editor)).json()
    assert nav["leads"] is None
    assert nav["reviews"] == 0

    me = (await client.get("/api/v1/auth/me", headers=editor)).json()
    assert me["staff_role"] == "editor"
    assert "content" in me["permissions"]
    assert "leads" not in me["permissions"]

    matrix = (await client.get(f"{ADMIN}/roles", headers=owner)).json()
    access = matrix["access"]
    assert set(access["owner"]) == {module["key"] for module in matrix["modules"]}
    access["editor"] = [*access["editor"], "leads"]
    saved = await client.put(f"{ADMIN}/roles", json={"access": access}, headers=owner)
    assert saved.status_code == 200, saved.text
    assert (await client.get(f"{ADMIN}/quotes", headers=editor)).status_code == 200

    # Only owners change the matrix (even if a role is given the team module).
    access["manager"] = [*access["manager"], "team"]
    await client.put(f"{ADMIN}/roles", json={"access": access}, headers=owner)
    _, manager = await _staff(db, StaffRole.MANAGER)
    refused = await client.put(f"{ADMIN}/roles", json={"access": access}, headers=manager)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "owners_only"
    assert editor_user.staff_role is StaffRole.EDITOR


async def test_inviting_a_team_member_end_to_end(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    owner_user, owner = await _staff(db, email="owner@pickasparky.test")
    invited = await client.post(
        f"{ADMIN}/team",
        json={"email": "new.editor@example.com", "full_name": "Nia Editor", "staff_role": "editor"},
        headers=owner,
    )
    assert invited.status_code == 201, invited.text
    assert invited.json()["joined"] is False
    token = fakes.emails.token_from("staff_invite")

    preview = await client.get("/api/v1/auth/invite", params={"token": token})
    assert preview.json() == {
        "email": "new.editor@example.com",
        "full_name": "Nia Editor",
        "staff_role": "editor",
    }
    accepted = await client.post(
        "/api/v1/auth/accept-invite", json={"token": token, "password": PASSWORD}
    )
    assert accepted.status_code == 200, accepted.text
    login = await client.post(
        "/api/v1/auth/login", json={"email": "new.editor@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    reused = await client.post(
        "/api/v1/auth/accept-invite", json={"token": token, "password": PASSWORD}
    )
    assert reused.status_code == 400

    members = (await client.get(f"{ADMIN}/team", headers=owner)).json()
    assert {(member["email"], member["joined"]) for member in members} == {
        ("owner@pickasparky.test", True),
        ("new.editor@example.com", True),
    }
    # The last owner cannot step down.
    demoted = await client.patch(
        f"{ADMIN}/team/{owner_user.id}", json={"staff_role": "manager"}, headers=owner
    )
    assert demoted.status_code == 409
    assert demoted.json()["error"]["code"] == "last_owner"


# ---- Settings -----------------------------------------------------------------------------


async def test_settings_drive_matching_and_team_alerts(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    _, owner = await _staff(db)
    current = (await client.get(f"{ADMIN}/settings", headers=owner)).json()
    assert current["settings"]["lead_matching"]["automatic"] is True
    assert current["status"]["sms_configured"] is False
    assert "secret" not in str(current).lower()

    sms = await client.put(
        f"{ADMIN}/settings",
        json={
            "lead_matching": {"automatic": True, "max_installers": 3},
            "notifications": {"email_alerts": True, "sms_alerts": True},
            "organisation": {"platform_name": "PickASparky", "support_email": "hi@example.com"},
        },
        headers=owner,
    )
    assert sms.status_code == 422

    saved = await client.put(
        f"{ADMIN}/settings",
        json={
            "lead_matching": {"automatic": False, "max_installers": 3},
            "notifications": {"email_alerts": True, "sms_alerts": False},
            "organisation": {"platform_name": "Sparky Hub", "support_email": "team@example.com"},
        },
        headers=owner,
    )
    assert saved.status_code == 200, saved.text
    assert "content" in fakes.revalidator.tags
    public = (await client.get("/api/v1/platform")).json()
    assert public == {"platform_name": "Sparky Hub", "support_email": "team@example.com"}

    # Automatic matching off: the request is held and the team is alerted at its address.
    await create_installer(db, "Waiting Installer")
    created = (await client.post("/api/v1/quotes", json=quote_payload())).json()
    assert created["held"] is True
    assert created["matched_installers"] == 0
    quote = await db.scalar(select(QuoteRequest))
    assert quote.status is QuoteStatus.NEW
    alert = fakes.emails.of("quote_unmatched")[-1]
    assert alert.to == "team@example.com"
    assert alert.context["held"] is True
    assert fakes.emails.of("quote_confirmation")[-1].context["held"] is True
    assert fakes.emails.of("quote_confirmation")[-1].from_name == "Sparky Hub"

    stages = (await client.get(f"{ADMIN}/quotes/stages", headers=owner)).json()
    assert stages["held"] == 1
    assert stages["open"] == 1
    assert (await client.get(f"{ADMIN}/nav", headers=owner)).json()["leads"] == 1


async def test_team_alerts_can_be_switched_off(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    _, owner = await _staff(db)
    await client.put(
        f"{ADMIN}/settings",
        json={
            "lead_matching": {"automatic": True, "max_installers": 5},
            "notifications": {"email_alerts": False, "sms_alerts": False},
            "organisation": {"platform_name": "PickASparky", "support_email": "a@example.com"},
        },
        headers=owner,
    )
    await client.post("/api/v1/quotes", json=quote_payload())  # nobody covers it
    assert fakes.emails.of("quote_unmatched") == []
    assert len(fakes.emails.of("quote_confirmation")) == 1


# ---- Held requests: choosing installers ---------------------------------------------------


async def test_team_sends_a_request_to_chosen_installers(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    _, owner = await _staff(db)
    near = await create_installer(db, "Near Installer")
    far = await create_installer(db, "Far Installer", at=STOCKPORT, location="stockport", radius=2)
    await client.post("/api/v1/quotes", json=quote_payload())  # matches "Near" only
    quote = await db.scalar(select(QuoteRequest))

    candidates = (await client.get(f"{ADMIN}/quotes/{quote.id}/candidates", headers=owner)).json()
    assert [c["business_name"] for c in candidates] == ["Near Installer", "Far Installer"]
    assert candidates[0]["already_matched"] is True
    assert candidates[0]["covers_address"] is True
    assert candidates[1]["covers_address"] is False
    assert candidates[1]["distance_miles"] > 4

    again = await client.post(
        f"{ADMIN}/quotes/{quote.id}/assign", json={"installer_ids": [str(near.id)]}, headers=owner
    )
    assert again.status_code == 409
    assigned = await client.post(
        f"{ADMIN}/quotes/{quote.id}/assign", json={"installer_ids": [str(far.id)]}, headers=owner
    )
    assert assigned.status_code == 200, assigned.text
    assert {match["installer_name"] for match in assigned.json()} == {
        "Near Installer",
        "Far Installer",
    }
    assert fakes.emails.of("new_lead")[-1].to == far.user.email
    shared = fakes.emails.of("quote_confirmation")[-1]
    assert shared.context["shared"] is True
    assert shared.context["installer_names"] == ["Far Installer"]

    listed = (await client.get(f"{ADMIN}/quotes", headers=owner)).json()["items"][0]
    assert (listed["installers_matched"], listed["quotes_sent"], listed["stage"]) == (2, 0, "open")
    assert listed["max_installers"] == 5
    one = (await client.get(f"{ADMIN}/quotes/{quote.id}", headers=owner)).json()
    assert one["reference"] == quote.reference
    assert one["installers_matched"] == 2


async def test_team_can_notify_more_installers_than_the_quote_limit_including_free_ones(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    _, owner = await _staff(db)
    await client.put(
        f"{ADMIN}/settings",
        json={
            "lead_matching": {"automatic": False, "max_installers": 1},
            "notifications": {"email_alerts": True, "sms_alerts": False},
            "organisation": {"platform_name": "PickASparky", "support_email": "a@example.com"},
        },
        headers=owner,
    )
    chosen = [
        await create_installer(db, "Pro One"),
        await create_installer(db, "Pro Two"),
        await create_installer(db, "Free One", plan=Plan.FREE),
    ]
    await client.post("/api/v1/quotes", json=quote_payload())
    quote = await db.scalar(select(QuoteRequest))

    candidates = (await client.get(f"{ADMIN}/quotes/{quote.id}/candidates", headers=owner)).json()
    assert {c["business_name"] for c in candidates} == {"Pro One", "Pro Two", "Free One"}
    assigned = await client.post(
        f"{ADMIN}/quotes/{quote.id}/assign",
        json={"installer_ids": [str(installer.id) for installer in chosen]},
        headers=owner,
    )
    assert assigned.status_code == 200, assigned.text
    assert len(assigned.json()) == 3
    leads = fakes.emails.of("new_lead")
    assert len(leads) == 3
    assert {email.context["max_quotes"] for email in leads} == {1}


# ---- Messages -----------------------------------------------------------------------------


async def test_admin_reads_every_conversation_and_writes_as_the_team(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    _, owner = await _staff(db)
    installer = await create_installer(db, "Chatty Installer")
    await client.post("/api/v1/quotes", json=quote_payload())
    lead = await db.scalar(select(QuoteMatch))
    started = await client.post(
        "/api/v1/installers/me/conversations",
        json={"lead_id": str(lead.id)},
        headers=auth_headers(installer.user),
    )
    conversation_id = started.json()["id"]

    listed = await client.get(f"{ADMIN}/conversations", params={"q": "chatty"}, headers=owner)
    assert [item["id"] for item in listed.json()["items"]] == [conversation_id]
    none = await client.get(f"{ADMIN}/conversations", params={"kind": "enquiry"}, headers=owner)
    assert none.json()["total"] == 0

    sent = await client.post(
        f"{ADMIN}/conversations/{conversation_id}/messages",
        json={"body": "Hi both, just checking everything is on track."},
        headers=owner,
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["sender"] == "team"
    team_emails = fakes.emails.of("conversation_team_message")
    assert {email.to for email in team_emails} == {"sam@example.com", installer.user.email}

    # The installer sees it as unread in their inbox.
    unread = await client.get(
        "/api/v1/installers/me/conversations",
        params={"unread": "true"},
        headers=auth_headers(installer.user),
    )
    assert unread.json()["total"] == 1

    leads = await client.get("/api/v1/installers/me/leads", headers=auth_headers(installer.user))
    progress = leads.json()["items"][0]["progress"]
    assert progress["installers_matched"] == 1
    assert progress["conversation_id"] == conversation_id
    assert progress["distance_miles"] == 0.0


# ---- Website content ----------------------------------------------------------------------


async def test_page_content_edit_publish_history_restore_and_reset(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    _, editor = await _staff(db, StaffRole.EDITOR)
    pages = (await client.get(f"{ADMIN}/content", headers=editor)).json()
    assert {"site", "home", "installers-hub", "contact", "location", "privacy"} <= {
        page["key"] for page in pages
    }

    document = (await client.get(f"{ADMIN}/content/contact", headers=editor)).json()
    assert document["customised"] is False
    assert {section["key"] for section in document["schema"]["sections"]} >= {"seo", "hero"}
    content = document["content"]
    original_title = content["hero"]["title"]
    content["hero"]["title"] = "Talk to a real person"
    content["seo"]["title"] = "Contact us"

    saved = await client.put(f"{ADMIN}/content/contact", json={"content": content}, headers=editor)
    assert saved.status_code == 200, saved.text
    assert saved.json()["customised"] is True
    assert "content:contact" in fakes.revalidator.tags
    public = (await client.get("/api/v1/content/contact")).json()
    assert public["content"]["hero"]["title"] == "Talk to a real person"

    content["hero"]["title"] = ""
    invalid = await client.put(
        f"{ADMIN}/content/contact", json={"content": content}, headers=editor
    )
    assert invalid.status_code == 422
    assert "hero.title" in invalid.json()["error"]["fields"]

    content["hero"]["lead"] = '<script>alert("x")</script>' + "a" * 10
    content["hero"]["title"] = "Second version"
    await client.put(f"{ADMIN}/content/contact", json={"content": content}, headers=editor)

    revisions = (await client.get(f"{ADMIN}/content/contact/revisions", headers=editor)).json()
    assert [revision["action"] for revision in revisions] == ["saved", "saved"]
    restored = await client.post(
        f"{ADMIN}/content/contact/revisions/{revisions[-1]['id']}/restore", headers=editor
    )
    assert restored.json()["content"]["hero"]["title"] == "Talk to a real person"

    reset = await client.delete(f"{ADMIN}/content/contact", headers=editor)
    assert reset.json()["customised"] is False
    assert reset.json()["content"]["hero"]["title"] == original_title
    public = (await client.get("/api/v1/content/contact")).json()
    assert public["content"]["hero"]["title"] == original_title
    assert (await client.get("/api/v1/content/nope")).status_code == 404

    site = await client.put(
        f"{ADMIN}/content/site",
        json={"content": (await client.get("/api/v1/content/site")).json()["content"]},
        headers=editor,
    )
    assert site.status_code == 200
    assert "content" in fakes.revalidator.tags

    uploaded = await client.post(
        f"{ADMIN}/media",
        files={"file": ("hero.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, "image/png")},
        headers=editor,
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["url"].startswith("https://images.test/content/")


async def test_list_items_can_be_added_removed_and_reordered(
    client: httpx.AsyncClient, db: AsyncSession
):
    _, owner = await _staff(db)
    content = (await client.get(f"{ADMIN}/content/faq", headers=owner)).json()["content"]
    items = content["homeowners"]["items"]
    first = items[0]
    content["homeowners"]["items"] = [*items[1:], first, {"question": "New?", "answer": "Yes."}]
    saved = await client.put(f"{ADMIN}/content/faq", json={"content": content}, headers=owner)
    assert saved.status_code == 200, saved.text
    stored = saved.json()["content"]["homeowners"]["items"]
    assert stored[-2] == first
    assert stored[-1] == {"question": "New?", "answer": "Yes."}

    content["homeowners"]["items"] = [
        {"question": "Unsafe link", "answer": "[x](javascript:alert(1))"}
    ]
    unsafe = await client.put(f"{ADMIN}/content/faq", json={"content": content}, headers=owner)

    about = (await client.get(f"{ADMIN}/content/about", headers=owner)).json()["content"]
    about["hero"]["image"] = "https://tracker.example/pixel.jpg"
    foreign = await client.put(f"{ADMIN}/content/about", json={"content": about}, headers=owner)
    assert foreign.status_code == 422
    assert "hero.image" in foreign.json()["error"]["fields"]
    about["hero"]["image"] = "https://res.cloudinary.com/demo/image/upload/hero.jpg"
    uploaded = await client.put(f"{ADMIN}/content/about", json={"content": about}, headers=owner)
    assert uploaded.status_code == 200
    # FAQ answers are plain text: the "link" is shown as typed, never as a link.
    assert unsafe.status_code == 200

    privacy = (await client.get(f"{ADMIN}/content/privacy", headers=owner)).json()["content"]
    privacy["body"]["sections"][0]["body"] = "See [this](javascript:alert(1))."
    script = await client.put(f"{ADMIN}/content/privacy", json={"content": privacy}, headers=owner)
    assert script.status_code == 422
    privacy["body"]["sections"][0]["body"] = "See [our terms](/terms-and-conditions/)."
    linked = await client.put(f"{ADMIN}/content/privacy", json={"content": privacy}, headers=owner)
    assert linked.status_code == 200


# ---- Locations ----------------------------------------------------------------------------


@pytest.fixture
async def kendal(db: AsyncSession) -> AsyncIterator[None]:
    """Locations survive between tests (they are seeded once), so remove the new page."""
    yield
    await db.rollback()
    await db.execute(delete(Location).where(Location.slug.like("kendal%")))
    await db.commit()


@pytest.mark.usefixtures("kendal")
async def test_new_location_pages_start_as_drafts(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    _, owner = await _staff(db)
    fakes.geocoder.places["LA9 4AA"] = fakes.geocoder.places["M1 1AA"].__class__(
        "LA9 4AA", 54.33, -2.75, "Kendal", "North West"
    )
    created = await client.post(
        f"{ADMIN}/locations",
        json={"name": "Kendal", "postcode": "LA9 4AA"},
        headers=owner,
    )
    assert created.status_code == 201, created.text
    assert created.json()["slug"] == "kendal"
    assert created.json()["is_published"] is False
    assert created.json()["region"] == "North West"

    assert (await client.get("/api/v1/locations/kendal")).status_code == 404
    public = (await client.get("/api/v1/locations")).json()
    assert "kendal" not in {item["slug"] for item in public}

    renamed = await client.patch(
        f"{ADMIN}/locations/kendal",
        json={"slug": "kendal-cumbria", "h1_heading": "EV chargers in Kendal"},
        headers=owner,
    )
    assert renamed.status_code == 200, renamed.text
    published = await client.patch(
        f"{ADMIN}/locations/kendal-cumbria",
        json={"is_published": True, "intro": "## Charging in Kendal\n\nPlenty to say."},
        headers=owner,
    )
    assert published.json()["is_published"] is True
    assert "locations" in fakes.revalidator.tags
    page = (await client.get("/api/v1/locations/kendal-cumbria")).json()
    assert page["h1_heading"] == "EV chargers in Kendal"

    locked = await client.patch(
        f"{ADMIN}/locations/kendal-cumbria", json={"slug": "kendal"}, headers=owner
    )
    assert locked.status_code == 422
    duplicate = await client.post(
        f"{ADMIN}/locations", json={"name": "Manchester", "postcode": "M1 1AA"}, headers=owner
    )
    assert duplicate.status_code == 422


# ---- Listings -----------------------------------------------------------------------------


async def test_team_adds_edits_and_imports_listings(
    client: httpx.AsyncClient, db: AsyncSession, fakes: Fakes
):
    _, owner = await _staff(db)
    created = await client.post(
        f"{ADMIN}/installers",
        json={
            "business_name": "Volt Masters",
            "contact_email": "hello@voltmasters.example",
            "phone": "0161 496 0000",
            "base_postcode": "M1 1AA",
            "accreditations": ["niceic", "ozev"],
        },
        headers=owner,
    )
    assert created.status_code == 201, created.text
    listing = created.json()
    assert (listing["source"], listing["is_claimed"], listing["status"]) == (
        "imported",
        False,
        "approved",
    )
    assert listing["location_slug"] == "manchester"
    assert "installers" in fakes.revalidator.tags

    edited = await client.patch(
        f"{ADMIN}/installers/{listing['id']}",
        json={"business_name": "Volt Masters Ltd", "base_postcode": "SK1 3XE"},
        headers=owner,
    )
    assert edited.status_code == 200, edited.text
    assert (edited.json()["business_name"], edited.json()["town"]) == (
        "Volt Masters Ltd",
        "Stockport",
    )
    empty = await client.patch(
        f"{ADMIN}/installers/{listing['id']}", json={"business_name": None}, headers=owner
    )
    assert empty.status_code == 422

    csv_file = (
        b"Business Name,Email,Phone,Postcode,Accreditations\n"
        b"Leeds Sparks,leeds@example.com,0113 496 0000,LS1 4AP,NICEIC; OZEV\n"
        b"Volt Masters Ltd,other@example.com,0161 496 0001,M1 1AA,\n"
        b"Nowhere Electric,nowhere@example.com,0161 496 0002,ZZ1 1ZZ,\n"
        b"Bad Phone,bad@example.com,123,M1 1AA,\n"
    )
    checked = await client.post(
        f"{ADMIN}/installers/import",
        files={"file": ("listings.csv", csv_file, "text/csv")},
        data={"dry_run": "true"},
        headers=owner,
    )
    assert checked.status_code == 200, checked.text
    report = checked.json()
    assert (report["rows"], report["created"]) == (4, 1)
    assert [row["row"] for row in report["skipped"]] == [3]
    assert sorted(row["row"] for row in report["errors"]) == [4, 5]
    count = len(list(await db.scalars(select(Installer))))
    assert count == 1

    imported = await client.post(
        f"{ADMIN}/installers/import",
        files={"file": ("listings.csv", csv_file, "text/csv")},
        data={"dry_run": "false"},
        headers=owner,
    )
    assert imported.json()["created"] == 1
    leeds = await db.scalar(select(Installer).where(Installer.business_name == "Leeds Sparks"))
    assert leeds is not None
    assert leeds.town == "Leeds"
    await db.refresh(leeds, ["accreditations"])
    assert {item.scheme.value for item in leeds.accreditations} == {"niceic", "ozev"}

    missing = await client.post(
        f"{ADMIN}/installers/import",
        files={"file": ("x.csv", b"name,phone\nA,1\n", "text/csv")},
        headers=owner,
    )
    assert missing.status_code == 422
    assert not await db.scalar(select(User).where(User.email == "leeds@example.com"))


async def test_http_revalidator_posts_tags_with_the_internal_key():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200 if len(seen) == 1 else 500)

    settings = get_settings().model_copy(
        update={"frontend_internal_url": "http://frontend:3000", "internal_api_key": "k" * 32}
    )
    revalidator = HttpRevalidator(settings, transport=httpx.MockTransport(handler))
    await revalidator.revalidate(["content:home", "content", "content"])
    assert str(seen[0].url) == "http://frontend:3000/api/revalidate/"
    assert seen[0].headers["X-Internal-Token"] == "k" * 32
    assert json.loads(seen[0].content) == {"tags": ["content", "content:home"]}
    await revalidator.revalidate(["blog"])  # a failing website never raises
    await revalidator.revalidate([])
    assert len(seen) == 2
