"""Application factory: middleware, exception handlers, routers and lifespan."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import httpx
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.endpoints import health
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.database import SessionFactory, engine
from app.core.exceptions import register_exception_handlers
from app.core.logging import REQUEST_ID_HEADER, RequestContextMiddleware, configure_logging
from app.core.middleware import (
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
    UnhandledErrorMiddleware,
)
from app.core.rate_limit import RateLimiter
from app.services import plans as plan_service
from app.services.email import SmtpEmailSender
from app.services.geocoding import PostcodesIOGeocoder
from app.services.revalidation import HttpRevalidator
from app.services.seeding import demo_postcodes
from app.services.storage import build_storage
from app.services.stripe_gateway import build_gateway

API_PREFIX = "/api/v1"
logger = logging.getLogger(__name__)
_GEOCODING_TIMEOUT_SECONDS = 5.0


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the shared external-service clients; release them on shutdown."""
    settings = get_settings()
    async with httpx.AsyncClient(timeout=_GEOCODING_TIMEOUT_SECONDS) as http_client:
        geocoder = PostcodesIOGeocoder(http_client, settings.postcodes_api_url)
        if settings.environment == "development":
            # Lets the demo postcodes be matched without reaching postcodes.io.
            geocoder.prime(demo_postcodes())
        app.state.geocoder = geocoder
        app.state.email_sender = SmtpEmailSender(settings)
        app.state.storage = build_storage(settings)
        app.state.billing_gateway = build_gateway(settings)
        app.state.revalidator = HttpRevalidator(settings)
        app.state.rate_limiter = RateLimiter(
            settings.rate_limit_storage_uri, enabled=settings.rate_limit_enabled
        )
        refresher = await _start_plan_catalogue(settings.plan_refresh_enabled)
        try:
            yield
        finally:
            if refresher is not None:
                refresher.cancel()
                with suppress(asyncio.CancelledError):
                    await refresher
    await engine.dispose()


async def _start_plan_catalogue(refresh: bool) -> asyncio.Task[None] | None:
    """Load the plan catalogue; keep it fresh so edits made on another worker arrive."""
    try:
        async with SessionFactory() as session:
            await plan_service.load_registry(session)
    except Exception:
        # Until a load succeeds every installer is treated as being on the default plan.
        logger.exception("Could not load the plan catalogue at start-up")
    return asyncio.create_task(plan_service.refresh_forever()) if refresh else None


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(json_logs=settings.is_production, debug=settings.debug)

    docs = settings.docs_are_enabled
    app = FastAPI(
        title="PickASparky API",
        version="1.0.0",
        description="Matches UK homeowners with vetted EV charger installers.",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    register_exception_handlers(app)

    # Added innermost first: the last middleware added is the first to see a request.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # Credentials: the Dashboard's refresh cookie (see `/auth/session`). Origins are an
        # explicit list, never `*`.
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER, "Retry-After"],
        max_age=600,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(SecurityHeadersMiddleware, no_store_prefix=f"{API_PREFIX}/auth")
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router)
    app.include_router(api_router, prefix=API_PREFIX)
    return app


app = create_app()
