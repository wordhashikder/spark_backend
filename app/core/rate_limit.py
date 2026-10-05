"""Per-client rate limiting built on `limits` (in-memory by default, Redis when configured)."""

import hmac
import ipaddress
import time
from collections.abc import Awaitable, Callable

from fastapi import Request
from limits import RateLimitItem, parse
from limits.aio.strategies import MovingWindowRateLimiter
from limits.storage import storage_from_string

from app.core.config import Settings, get_settings
from app.core.exceptions import RateLimitedError

INTERNAL_TOKEN_HEADER = "X-Internal-Token"  # noqa: S105 - a header name, not a credential
CLIENT_IP_HEADER = "X-Client-IP"
_ASYNC_PREFIX = "async+"


class RateLimiter:
    """Moving-window limiter keyed by `(scope, client)`."""

    def __init__(self, storage_uri: str, *, enabled: bool) -> None:
        self.enabled = enabled
        uri = storage_uri if storage_uri.startswith(_ASYNC_PREFIX) else _ASYNC_PREFIX + storage_uri
        self._strategy = MovingWindowRateLimiter(storage_from_string(uri))

    async def hit(self, scope: str, limit: RateLimitItem, client: str) -> None:
        """Record one request; raise `RateLimitedError` when the client is over the limit."""
        if not self.enabled:
            return
        if await self._strategy.hit(limit, scope, client):
            return
        stats = await self._strategy.get_window_stats(limit, scope, client)
        raise RateLimitedError(retry_after_seconds=int(stats.reset_time - time.time()) + 1)


def _is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def client_ip(request: Request, settings: Settings) -> str:
    """Resolve the visitor's IP address.

    The Next.js server forwards the visitor's address in `X-Client-IP`; it is trusted only
    when the request also proves it comes from our frontend via `X-Internal-Token`.
    Everything else is identified by the peer address uvicorn resolved (proxy headers included).
    """
    token = request.headers.get(INTERNAL_TOKEN_HEADER)
    if settings.internal_api_key and token:
        trusted = hmac.compare_digest(token.encode(), settings.internal_api_key.encode())
        supplied = request.headers.get(CLIENT_IP_HEADER, "").strip()
        if trusted and _is_ip_address(supplied):
            return supplied
    return request.client.host if request.client else "unknown"


def rate_limit(scope: str, limit: str) -> Callable[[Request], Awaitable[None]]:
    """Build a FastAPI dependency enforcing `limit` (e.g. `"10/minute"`) per client IP."""
    item = parse(limit)

    async def enforce(request: Request) -> None:
        limiter: RateLimiter = request.app.state.rate_limiter
        await limiter.hit(scope, item, client_ip(request, get_settings()))

    return enforce
