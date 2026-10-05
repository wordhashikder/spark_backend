"""Cross-cutting behaviour: health, the error envelope, headers, limits and configuration."""

import httpx
import pytest
from fastapi import FastAPI
from limits import parse
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import RateLimitedError
from app.core.rate_limit import RateLimiter
from app.services.geocoding import (
    GeocodingUnavailableError,
    PostcodeNotFoundError,
    PostcodesIOGeocoder,
    normalise_postcode,
)
from tests.helpers import Fakes, quote_payload

LOGIN = {"email": "nobody@example.com", "password": "whatever-123"}


async def test_health_is_served_at_root_and_under_the_api_prefix(client: httpx.AsyncClient):
    for path in ("/health", "/api/v1/health", "/health/ready", "/api/v1/health/ready"):
        response = await client.get(path)
        assert response.status_code == 200, path
        assert response.json() == {"status": "ok"}


async def test_unknown_route_uses_the_error_envelope(client: httpx.AsyncClient):
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not Found"}}


async def test_wrong_method_uses_the_error_envelope(client: httpx.AsyncClient):
    response = await client.delete("/api/v1/quotes")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


async def test_validation_errors_are_keyed_by_field(client: httpx.AsyncClient):
    response = await client.post("/api/v1/contact", json={"name": "A", "email": "not-an-email"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["fields"]["name"] == "Must be at least 2 characters."
    assert error["fields"]["email"] == "Enter a valid email address."
    assert error["fields"]["subject"] == "This field is required."
    assert error["fields"]["message"] == "This field is required."


async def test_malformed_json_uses_the_error_envelope(client: httpx.AsyncClient):
    response = await client.post(
        "/api/v1/contact", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_unhandled_errors_return_a_generic_500(client: httpx.AsyncClient, fakes: Fakes):
    async def explode(postcode: str):
        raise RuntimeError("secret database detail")

    fakes.geocoder.lookup = explode
    response = await client.post("/api/v1/quotes", json=quote_payload())
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret" not in response.text
    assert response.headers["X-Request-ID"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


async def test_security_headers_and_request_id(client: httpx.AsyncClient):
    response = await client.get("/health", headers={"X-Request-ID": "trace-12345678"})
    assert response.headers["X-Request-ID"] == "trace-12345678"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "Cache-Control" not in response.headers

    generated = await client.get("/health", headers={"X-Request-ID": "bad id\twith spaces"})
    assert generated.headers["X-Request-ID"] != "bad id\twith spaces"
    assert len(generated.headers["X-Request-ID"]) == 32


async def test_auth_responses_are_never_cached(client: httpx.AsyncClient):
    response = await client.post("/api/v1/auth/login", json=LOGIN)
    assert response.headers["Cache-Control"] == "no-store"
    with_token = await client.get("/api/v1/installers/me", headers={"Authorization": "Bearer x"})
    assert with_token.headers["Cache-Control"] == "no-store"


async def test_cors_allows_only_configured_origins(client: httpx.AsyncClient):
    allowed = await client.get("/health", headers={"Origin": "https://frontend.test"})
    assert allowed.headers["Access-Control-Allow-Origin"] == "https://frontend.test"
    assert "Access-Control-Allow-Credentials" not in allowed.headers
    denied = await client.get("/health", headers={"Origin": "https://evil.test"})
    assert "Access-Control-Allow-Origin" not in denied.headers


async def test_oversized_json_body_is_rejected(client: httpx.AsyncClient):
    response = await client.post("/api/v1/contact", json={"message": "x" * (1024 * 1024 + 1)})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_oversized_streamed_body_is_rejected(client: httpx.AsyncClient):
    async def chunks():
        for _ in range(5):
            yield b"x" * (300 * 1024)

    response = await client.post(
        "/api/v1/contact", content=chunks(), headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_rate_limiter_blocks_after_the_limit_and_reports_retry_after():
    limiter = RateLimiter("memory://", enabled=True)
    limit = parse("2/minute")
    await limiter.hit("login", limit, "203.0.113.1")
    await limiter.hit("login", limit, "203.0.113.1")
    with pytest.raises(RateLimitedError) as blocked:
        await limiter.hit("login", limit, "203.0.113.1")
    assert 1 <= int(blocked.value.headers["Retry-After"]) <= 61
    # Other clients and other scopes are counted separately.
    await limiter.hit("login", limit, "203.0.113.2")
    await limiter.hit("register", limit, "203.0.113.1")


async def test_disabled_rate_limiter_never_blocks():
    limiter = RateLimiter("memory://", enabled=False)
    for _ in range(5):
        await limiter.hit("login", parse("1/hour"), "203.0.113.1")


async def test_rate_limit_response_and_trusted_client_ip(client: httpx.AsyncClient, app: FastAPI):
    original = app.state.rate_limiter
    app.state.rate_limiter = RateLimiter("memory://", enabled=True)
    try:
        for _ in range(10):
            assert (await client.post("/api/v1/auth/login", json=LOGIN)).status_code == 401
        blocked = await client.post("/api/v1/auth/login", json=LOGIN)
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "rate_limited"
        assert int(blocked.headers["Retry-After"]) >= 1

        # A visitor IP forwarded by the frontend gets its own bucket, but only with the token.
        forwarded = {"X-Client-IP": "198.51.100.7"}
        spoofed = await client.post("/api/v1/auth/login", json=LOGIN, headers=forwarded)
        assert spoofed.status_code == 429
        trusted = await client.post(
            "/api/v1/auth/login",
            json=LOGIN,
            headers=forwarded | {"X-Internal-Token": "test-internal-key"},
        )
        assert trusted.status_code == 401
    finally:
        app.state.rate_limiter = original


def test_settings_rewrite_plain_postgres_urls():
    for url in ("postgres://u:p@db:5432/app", "postgresql://u:p@db:5432/app"):
        settings = Settings(_env_file=None, secret_key="x" * 32, database_url=url)
        assert settings.database_url == "postgresql+asyncpg://u:p@db:5432/app"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, secret_key="x" * 32, database_url="mysql://u:p@db/app")


def test_settings_require_a_strong_secret_in_production():
    url = "postgresql+asyncpg://u:p@db/app"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production", secret_key="short", database_url=url)
    with pytest.raises(ValidationError, match="INTERNAL_API_KEY"):
        Settings(
            _env_file=None,
            environment="production",
            secret_key="x" * 32,
            database_url=url,
            internal_api_key="",
        )
    production = Settings(
        _env_file=None,
        environment="production",
        secret_key="x" * 32,
        database_url=url,
        allowed_hosts="api.example.com, backend",
        cors_origins="https://a.example, https://b.example",
        docs_enabled="",
    )
    assert production.docs_are_enabled is False
    assert production.cors_origins == ["https://a.example", "https://b.example"]
    assert production.trusted_hosts == ["api.example.com", "backend", "localhost", "127.0.0.1"]


def test_postcodes_are_normalised():
    assert normalise_postcode(" m1 1aa ") == "M1 1AA"
    assert normalise_postcode("SW1A1AA") == "SW1A 1AA"
    assert normalise_postcode("ec1a  1bb") == "EC1A 1BB"
    for invalid in ("", "12345", "M1", "ZZZ 999", "M1 1AAA"):
        assert normalise_postcode(invalid) is None


async def test_postcodes_io_geocoder_maps_responses_and_caches():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/M11AA"):
            result = {
                "postcode": "M1 1AA",
                "latitude": 53.48,
                "longitude": -2.24,
                "admin_district": "Manchester",
                "region": "North West",
            }
            return httpx.Response(200, json={"status": 200, "result": result})
        if request.url.path.endswith("/ZZ99ZZ"):
            return httpx.Response(404, json={"status": 404, "error": "Postcode not found"})
        if request.url.path.endswith("/M22BB"):
            raise httpx.ConnectTimeout("timed out")
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        geocoder = PostcodesIOGeocoder(http_client, "https://postcodes.test")
        place = await geocoder.lookup("M1 1AA")
        assert (place.postcode, place.district, place.region) == (
            "M1 1AA",
            "Manchester",
            "North West",
        )
        assert await geocoder.lookup("M1 1AA") == place
        assert calls == ["/postcodes/M11AA"]

        with pytest.raises(PostcodeNotFoundError):
            await geocoder.lookup("ZZ9 9ZZ")
        with pytest.raises(GeocodingUnavailableError):
            await geocoder.lookup("M2 2BB")
        with pytest.raises(GeocodingUnavailableError):
            await geocoder.lookup("M3 3CC")
