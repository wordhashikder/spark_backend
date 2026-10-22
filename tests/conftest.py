"""Test harness: a real `pickasparky_test` PostgreSQL database and fakes for external services."""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://pickasparky:pickasparky@127.0.0.1:5432/pickasparky_test",
)
# Settings are read at import time, so the environment is fixed before the app is imported.
# Every variable a developer's `.env` might define is pinned here.
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DEBUG": "false",
        "SECRET_KEY": "test-secret-key-that-is-long-enough-for-hs256",
        "DATABASE_URL": TEST_DATABASE_URL,
        "FRONTEND_URL": "https://frontend.test",
        "CORS_ORIGINS": "https://frontend.test",
        "ALLOWED_HOSTS": "*",
        "INTERNAL_API_KEY": "test-internal-key",
        "DOCS_ENABLED": "",
        "SUPPORT_EMAIL": "support@pickasparky.test",
        "EMAIL_FROM": "no-reply@pickasparky.test",
        "SMTP_HOST": "",
        "CLOUDINARY_CLOUD_NAME": "",
        "CLOUDINARY_API_KEY": "",
        "CLOUDINARY_API_SECRET": "",
        "STRIPE_SECRET_KEY": "sk_test_dummy",
        "STRIPE_WEBHOOK_SECRET": "whsec_test_dummy",
        "RATE_LIMIT_STORAGE_URI": "memory://",
        "MAX_QUOTE_MATCHES": "5",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "15",
        "REFRESH_TOKEN_EXPIRE_DAYS": "30",
    }
)

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.database import SessionFactory, engine  # noqa: E402
from app.main import app as application  # noqa: E402
from app.models import Base  # noqa: E402
from app.services import plans as plan_service  # noqa: E402
from app.services import platform, seeding  # noqa: E402
from tests.helpers import Fakes  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent
_PRESERVED_TABLES = {"locations"}
# The plan catalogue the migration seeds; every test starts from it (tests may edit plans).
_PLAN_TABLES = ("plans", "plan_prices")
_plan_snapshot: dict[str, list[dict[str, object]]] = {}


async def _recreate_database() -> None:
    url = make_url(TEST_DATABASE_URL)
    connection = await asyncpg.connect(
        host=url.host, port=url.port, user=url.username, password=url.password, database="postgres"
    )
    try:
        await connection.execute(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)')
        await connection.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await connection.close()


async def _snapshot_plans() -> None:
    url = make_url(TEST_DATABASE_URL)
    connection = await asyncpg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        database=url.database,
    )
    try:
        for table in _PLAN_TABLES:
            rows = await connection.fetch(f"SELECT * FROM {table}")  # noqa: S608 - fixed names
            _plan_snapshot[table] = [dict(row) for row in rows]
    finally:
        await connection.close()


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    """Build the schema from an empty database with the real Alembic migration."""
    asyncio.run(_recreate_database())
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
    asyncio.run(_snapshot_plans())


async def _restore_plans() -> None:
    async with engine.begin() as connection:
        for table in _PLAN_TABLES:
            for row in _plan_snapshot[table]:
                columns = ", ".join(row)
                values = ", ".join(f":{column}" for column in row)
                await connection.execute(
                    text(f"INSERT INTO {table} ({columns}) VALUES ({values})"),  # noqa: S608
                    row,
                )
    async with SessionFactory() as session:
        await plan_service.load_registry(session)


@pytest.fixture(scope="session")
async def app(database: None) -> AsyncIterator[FastAPI]:
    async with SessionFactory() as session:
        await seeding.seed_locations(session)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture(autouse=True)
async def clean_tables(app: FastAPI) -> AsyncIterator[None]:
    yield
    tables = ", ".join(
        table.name for table in Base.metadata.sorted_tables if table.name not in _PRESERVED_TABLES
    )
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {tables} CASCADE"))
    await _restore_plans()
    platform.clear_cache()


@pytest.fixture
def fakes(app: FastAPI) -> Iterator[Fakes]:
    """Swap every external integration for a recording fake for the duration of a test."""
    originals = {name: getattr(app.state, name) for name in Fakes.STATE_NAMES}
    fakes = Fakes()
    fakes.install(app)
    yield fakes
    for name, original in originals.items():
        setattr(app.state, name, original)


@pytest.fixture
async def client(app: FastAPI, fakes: Fakes) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
async def db(app: FastAPI) -> AsyncIterator[AsyncSession]:
    """A session for arranging data and inspecting results directly."""
    async with SessionFactory() as session:
        yield session
