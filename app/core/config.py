"""Application settings, loaded from the environment (and a local `.env` file)."""

from functools import lru_cache
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

MIN_PRODUCTION_SECRET_LENGTH = 32
_ASYNC_SCHEME = "postgresql+asyncpg://"
_REWRITTEN_SCHEMES = ("postgres://", "postgresql://")
# Loopback names stay trusted so the container health check can reach the API.
_LOOPBACK_HOSTS = ("localhost", "127.0.0.1")

CommaSeparated = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    """Every runtime setting; `.env.example` documents each variable."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Literal["development", "production", "test"] = "development"
    debug: bool = False
    secret_key: str
    database_url: str
    cors_origins: CommaSeparated = []
    allowed_hosts: CommaSeparated = ["*"]
    frontend_url: str = "http://localhost:3000"
    internal_api_key: str | None = None
    docs_enabled: bool | None = None

    access_token_expire_minutes: int = Field(default=15, ge=1)
    refresh_token_expire_days: int = Field(default=30, ge=1)

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = False
    smtp_start_tls: bool = True
    email_from: str = "no-reply@pickasparky.co.uk"
    email_from_name: str = "PickASparky"
    support_email: str = "hello@pickasparky.co.uk"

    cloudinary_cloud_name: str | None = None
    cloudinary_api_key: str | None = None
    cloudinary_api_secret: str | None = None
    cloudinary_folder: str = "pickasparky"

    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_pro: str | None = None
    stripe_price_premium: str | None = None

    rate_limit_storage_uri: str = "memory://"
    postcodes_api_url: str = "https://api.postcodes.io"
    max_quote_matches: int = Field(default=5, ge=1, le=20)

    @field_validator("cors_origins", "allowed_hosts", mode="before")
    @classmethod
    def _split_comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator(
        "internal_api_key",
        "smtp_host",
        "smtp_username",
        "smtp_password",
        "cloudinary_cloud_name",
        "cloudinary_api_key",
        "cloudinary_api_secret",
        "stripe_secret_key",
        "stripe_webhook_secret",
        "stripe_price_pro",
        "stripe_price_premium",
        "docs_enabled",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """Treat `KEY=` lines copied from `.env.example` as "not configured"."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("database_url")
    @classmethod
    def _use_asyncpg_driver(cls, value: str) -> str:
        """Accept the plain `postgres://` / `postgresql://` form that Coolify hands out."""
        for scheme in _REWRITTEN_SCHEMES:
            if value.startswith(scheme):
                return _ASYNC_SCHEME + value.removeprefix(scheme)
        if not value.startswith(_ASYNC_SCHEME):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")
        return value

    @field_validator("frontend_url", "postcodes_api_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if self.is_production and len(self.secret_key) < MIN_PRODUCTION_SECRET_LENGTH:
            raise ValueError(
                f"SECRET_KEY must be at least {MIN_PRODUCTION_SECRET_LENGTH} characters "
                "in production"
            )
        if self.is_production and not self.internal_api_key:
            # Without it every visitor shares the frontend server's IP address, so the
            # public-form rate limits would throttle the whole site as one client.
            raise ValueError("INTERNAL_API_KEY is required in production")
        if self.smtp_use_tls and self.smtp_start_tls:
            raise ValueError("SMTP_USE_TLS and SMTP_START_TLS are mutually exclusive")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def docs_are_enabled(self) -> bool:
        """`DOCS_ENABLED` wins when set; otherwise docs are on everywhere except production."""
        if self.docs_enabled is not None:
            return self.docs_enabled
        return not self.is_production

    @property
    def trusted_hosts(self) -> list[str]:
        if "*" in self.allowed_hosts:
            return ["*"]
        return [*self.allowed_hosts, *(h for h in _LOOPBACK_HOSTS if h not in self.allowed_hosts)]

    @property
    def rate_limit_enabled(self) -> bool:
        return self.environment != "test"

    @property
    def smtp_configured(self) -> bool:
        return self.smtp_host is not None

    @property
    def cloudinary_configured(self) -> bool:
        return all(
            (self.cloudinary_cloud_name, self.cloudinary_api_key, self.cloudinary_api_secret)
        )

    @property
    def stripe_configured(self) -> bool:
        return all(
            (
                self.stripe_secret_key,
                self.stripe_webhook_secret,
                self.stripe_price_pro,
                self.stripe_price_premium,
            )
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
