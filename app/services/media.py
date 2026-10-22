"""Move the images that ship with the website into Cloudinary.

The seed data (town photos, blog covers, the showcase installers' logos and galleries) points
at files bundled with the website (`/images/...`). In production every image must live in
Cloudinary, so this service uploads each bundled file once and rewrites the database row to
the Cloudinary address. It only touches rows that still point at a bundled file, so it is safe
to run again and never replaces an image an admin uploaded.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BlogPost, Installer, InstallerPhoto, Location
from app.services.storage import ImageStorage, StoredImage, validate_image

logger = logging.getLogger(__name__)

BUNDLED_PREFIX = "/images/"
_FETCH_TIMEOUT_SECONDS = 30


class MediaSource(Protocol):
    """Where the bundled files are read from."""

    async def read(self, path: str) -> bytes | None: ...


class DirectorySource:
    """The website's `public/` folder on disk."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def read(self, path: str) -> bytes | None:
        candidate = (self._root / path.lstrip("/")).resolve()
        if not candidate.is_relative_to(self._root) or not candidate.is_file():
            return None
        return candidate.read_bytes()


class HttpSource:
    """The running website (for servers that only have the backend)."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def read(self, path: str) -> bytes | None:
        try:
            async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_SECONDS) as client:
                response = await client.get(f"{self._base_url}{path}")
        except httpx.HTTPError:
            return None
        return response.content if response.status_code == httpx.codes.OK else None


def _sample(paths: list[str], limit: int = 3) -> str:
    shown = ", ".join(paths[:limit])
    return f"{shown}, ..." if len(paths) > limit else shown


@dataclass(slots=True)
class MediaReport:
    uploaded: int = 0
    rewritten: int = 0
    missing: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.missing and not self.failed

    def summary(self) -> str:
        parts = [f"{self.uploaded} files uploaded to Cloudinary, {self.rewritten} records updated"]
        if self.missing:
            parts.append(f"{len(self.missing)} bundled files not found ({_sample(self.missing)})")
        if self.failed:
            parts.append(f"{len(self.failed)} uploads failed ({_sample(self.failed)})")
        return "; ".join(parts) + "."


@dataclass(slots=True)
class _Run:
    storage: ImageStorage
    source: MediaSource
    report: MediaReport
    dry_run: bool
    cache: dict[str, StoredImage | None] = field(default_factory=dict)

    async def stored(self, path: str, folder: str) -> StoredImage | None:
        """Upload `path` once; later rows that use the same file reuse the result."""
        if path in self.cache:
            return self.cache[path]
        result: StoredImage | None = None
        data = await self.source.read(path)
        if data is None:
            self.report.missing.append(path)
        elif self.dry_run:
            self.report.uploaded += 1
        else:
            try:
                validate_image(data)
                result = await self.storage.upload(data, folder=folder)
                self.report.uploaded += 1
            except Exception:
                logger.warning("Could not upload %s", path, exc_info=True)
                self.report.failed.append(path)
        self.cache[path] = result
        return result


async def migrate_bundled_media(
    session: AsyncSession,
    storage: ImageStorage,
    source: MediaSource,
    *,
    dry_run: bool = False,
) -> MediaReport:
    """Upload every bundled image the database still points at and update the rows."""
    run = _Run(storage=storage, source=source, report=MediaReport(), dry_run=dry_run)

    locations = await session.scalars(
        select(Location).where(Location.image_url.startswith(BUNDLED_PREFIX))
    )
    for location in locations:
        stored = await run.stored(location.image_url or "", "locations")
        if stored:
            location.image_url, location.image_public_id = stored.url, stored.public_id
            run.report.rewritten += 1

    posts = await session.scalars(
        select(BlogPost).where(BlogPost.cover_image_url.startswith(BUNDLED_PREFIX))
    )
    for post in posts:
        stored = await run.stored(post.cover_image_url or "", "blog")
        if stored:
            post.cover_image_url, post.cover_image_public_id = stored.url, stored.public_id
            run.report.rewritten += 1

    installers = await session.scalars(
        select(Installer).where(Installer.logo_url.startswith(BUNDLED_PREFIX))
    )
    for installer in installers:
        stored = await run.stored(installer.logo_url or "", "logos")
        if stored:
            installer.logo_url, installer.logo_public_id = stored.url, stored.public_id
            run.report.rewritten += 1

    photos = await session.scalars(
        select(InstallerPhoto).where(InstallerPhoto.url.startswith(BUNDLED_PREFIX))
    )
    for photo in photos:
        stored = await run.stored(photo.url, "gallery")
        if stored:
            photo.url, photo.public_id = stored.url, stored.public_id
            run.report.rewritten += 1

    if dry_run:
        await session.rollback()
    else:
        await session.commit()
    return run.report
