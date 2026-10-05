"""Security headers, request-size limits and the catch-all error boundary (plain ASGI)."""

import logging

from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.exceptions import PayloadTooLargeError, error_response

logger = logging.getLogger(__name__)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
MAX_JSON_BODY_BYTES = 1024 * 1024
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
# Room for multipart boundaries, part headers and the small text fields beside the file.
_MULTIPART_OVERHEAD_BYTES = 64 * 1024


class SecurityHeadersMiddleware:
    """Add the baseline security headers; forbid caching of anything account-specific."""

    def __init__(self, app: ASGIApp, *, no_store_prefix: str) -> None:
        self.app = app
        self.no_store_prefix = no_store_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        private = scope["path"].startswith(self.no_store_prefix) or (
            "authorization" in Headers(scope=scope)
        )

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.update(SECURITY_HEADERS)
                if private:
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodySizeLimitMiddleware:
    """Reject oversized bodies: 1 MB by default, 5 MB (plus framing) for multipart uploads."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        is_multipart = headers.get("content-type", "").startswith("multipart/form-data")
        limit = (
            MAX_UPLOAD_BYTES + _MULTIPART_OVERHEAD_BYTES if is_multipart else MAX_JSON_BODY_BYTES
        )

        declared = headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            response = error_response(
                PayloadTooLargeError.status_code,
                PayloadTooLargeError.code,
                PayloadTooLargeError.message,
            )
            await response(scope, receive, send)
            return

        received = 0

        async def receive_within_limit() -> Message:
            """Enforce the limit on streamed bodies that declared no (or a false) length."""
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(status_code=PayloadTooLargeError.status_code)
            return message

        await self.app(scope, receive_within_limit, send)


class UnhandledErrorMiddleware:
    """Innermost middleware: turn any unhandled exception into the 500 error envelope.

    Sitting inside the other middleware means the response still receives the request id,
    security and CORS headers, and the log line is written with the request id in context.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            logger.exception("Unhandled error on %s %s", scope["method"], scope["path"])
            if response_started:
                raise
            response = error_response(
                500, "internal_error", "Something went wrong on our side. Please try again."
            )
            await response(scope, receive, send)
