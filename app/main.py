"""Application factory: middleware, exception handlers, routers and lifespan."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.endpoints import health
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.database import engine
from app.core.exceptions import register_exception_handlers
from app.core.logging import REQUEST_ID_HEADER, RequestContextMiddleware, configure_logging
from app.core.middleware import (
    BodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
    UnhandledErrorMiddleware,
)
from app.core.rate_limit import RateLimiter
from app.services.billing import build_gateway
from app.services.email import SmtpEmailSender
from app.services.geocoding import PostcodesIOGeocoder
from app.services.seeding import demo_postcodes
from app.services.storage import build_storage

API_PREFIX = "/api/v1"
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
        app.state.rate_limiter = RateLimiter(
            settings.rate_limit_storage_uri, enabled=settings.rate_limit_enabled
        )
        yield
    await engine.dispose()


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
