"""Tell the website to refresh cached pages after the back office changes content.

The website caches API responses by tag (`content:home`, `locations`, `blog`...). After an
edit the API calls the website's `/api/revalidate` route with the shared
`INTERNAL_API_KEY`, so the change is live within seconds instead of after the cache
expires. It runs after the response; a failure is logged and the page simply refreshes
on its normal schedule (at most a few minutes later).
"""

import logging
from collections.abc import Iterable
from typing import Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)
_TIMEOUT_SECONDS = 5.0


class Revalidator(Protocol):
    async def revalidate(self, tags: Iterable[str]) -> None: ...


class HttpRevalidator:
    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        base = settings.frontend_internal_url or settings.frontend_url
        # The website's pages end with a slash (`trailingSlash`), so post there directly.
        self._url = f"{base.rstrip('/')}/api/revalidate/"
        self._key = settings.internal_api_key
        self._transport = transport

    async def revalidate(self, tags: Iterable[str]) -> None:
        tags = sorted(set(tags))
        if not tags or not self._key:
            return
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT_SECONDS, transport=self._transport
            ) as client:
                response = await client.post(
                    self._url, json={"tags": tags}, headers={"X-Internal-Token": self._key}
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Could not refresh website cache for %s: %s", tags, exc)
        else:
            logger.info("Refreshed website cache for %s", tags)
