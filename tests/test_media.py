"""Moving the images bundled with the website into Cloudinary."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionFactory
from app.models import BlogPost, Installer, InstallerPhoto, Location
from app.services import media, seeding
from tests.helpers import FakeStorage

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture(autouse=True)
async def bundled_town_photos(app: object) -> AsyncIterator[None]:
    """Town rows outlive each test, so put the seed's bundled photos back around these."""

    async def restore() -> None:
        async with SessionFactory() as session:
            for row in seeding._location_rows():
                await session.execute(
                    update(Location)
                    .where(Location.slug == row["slug"])
                    .values(image_url=row["image_url"], image_public_id=None)
                )
            await session.commit()

    await restore()
    yield
    await restore()


class FakeSource:
    def __init__(self, *, missing: frozenset[str] = frozenset()) -> None:
        self.missing = missing
        self.reads: list[str] = []

    async def read(self, path: str) -> bytes | None:
        self.reads.append(path)
        return None if path in self.missing else PNG


async def _local_locations(db: AsyncSession) -> list[Location]:
    rows = await db.scalars(select(Location).where(Location.image_url.startswith("/images/")))
    return list(rows)


async def test_seeded_town_photos_move_to_cloudinary(db: AsyncSession) -> None:
    await seeding.seed_locations(db)
    before = len(await _local_locations(db))
    assert before > 20
    storage, source = FakeStorage(), FakeSource()

    report = await media.migrate_bundled_media(db, storage, source)

    assert report.clean
    assert report.rewritten == report.uploaded == before == len(storage.uploaded)
    assert await _local_locations(db) == []
    moved = await db.scalar(select(Location).where(Location.slug == "manchester"))
    assert moved is not None
    assert str(moved.image_url).startswith("https://images.test/")
    assert str(moved.image_public_id).startswith("locations/")
    assert moved.image_alt  # the description stays


async def test_running_again_uploads_nothing(db: AsyncSession) -> None:
    await seeding.seed_locations(db)
    await media.migrate_bundled_media(db, FakeStorage(), FakeSource())
    storage = FakeStorage()

    report = await media.migrate_bundled_media(db, storage, FakeSource())

    assert (report.uploaded, report.rewritten, storage.uploaded) == (0, 0, [])


async def test_seeding_again_keeps_the_cloudinary_photo(db: AsyncSession) -> None:
    await seeding.seed_locations(db)
    await media.migrate_bundled_media(db, FakeStorage(), FakeSource())

    await seeding.seed_locations(db)

    assert await _local_locations(db) == []


async def test_an_image_an_admin_uploaded_is_never_replaced(db: AsyncSession) -> None:
    await seeding.seed_locations(db)
    town = await db.scalar(select(Location).where(Location.slug == "cardiff"))
    assert town is not None
    town.image_url = "https://res.cloudinary.com/demo/image/upload/mine.jpg"
    town.image_public_id = "pickasparky/locations/mine"
    await db.commit()

    await media.migrate_bundled_media(db, FakeStorage(), FakeSource())

    await db.refresh(town)
    assert town.image_url == "https://res.cloudinary.com/demo/image/upload/mine.jpg"
    assert town.image_public_id == "pickasparky/locations/mine"


async def test_a_file_used_twice_is_uploaded_once(db: AsyncSession) -> None:
    await seeding.seed_locations(db)
    towns = list(await db.scalars(select(Location).limit(2)))
    for town in towns:
        town.image_url = "/images/locations/shared.jpg"
    await db.commit()
    for other in await _local_locations(db):
        if other.image_url != "/images/locations/shared.jpg":
            other.image_url = None
    await db.commit()
    storage = FakeStorage()

    report = await media.migrate_bundled_media(db, storage, FakeSource())

    assert len(storage.uploaded) == 1
    assert report.rewritten == 2


async def test_a_missing_file_is_reported_and_left_alone(db: AsyncSession) -> None:
    await seeding.seed_locations(db)
    source = FakeSource(missing=frozenset({"/images/locations/manchester.jpg"}))

    report = await media.migrate_bundled_media(db, FakeStorage(), source)

    assert not report.clean
    assert report.missing == ["/images/locations/manchester.jpg"]
    left = await _local_locations(db)
    assert [town.slug for town in left] == ["manchester"]


async def test_a_dry_run_changes_nothing(db: AsyncSession) -> None:
    await seeding.seed_locations(db)
    before = len(await _local_locations(db))
    storage = FakeStorage()

    report = await media.migrate_bundled_media(db, storage, FakeSource(), dry_run=True)

    assert report.uploaded == before
    assert storage.uploaded == []
    assert len(await _local_locations(db)) == before


async def test_blog_covers_and_showcase_installer_images_move_too(db: AsyncSession) -> None:
    await seeding.seed_locations(db)
    await seeding.seed_blog(db)
    await seeding.seed_demo(db)
    storage = FakeStorage()

    report = await media.migrate_bundled_media(db, storage, FakeSource())

    assert report.clean
    covers = list(await db.scalars(select(BlogPost.cover_image_url)))
    logos = list(
        await db.scalars(select(Installer.logo_url).where(Installer.logo_url.is_not(None)))
    )
    gallery = list(await db.scalars(select(InstallerPhoto.url)))
    assert covers
    assert logos
    assert gallery
    for url in [*covers, *logos, *gallery]:
        assert url is None or not url.startswith("/images/")
    folders = {public_id.split("/")[0] for public_id in storage.uploaded}
    assert {"locations", "blog", "logos", "gallery"} <= folders
