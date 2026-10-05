"""Async SQLAlchemy engine and the per-request session dependency."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database_url,
    echo=_settings.debug and not _settings.is_production,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=10,
    pool_recycle=1800,
)

SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield one session per request.

    Services commit explicitly once a use case succeeds; anything left uncommitted
    (including work interrupted by an exception) is rolled back when the session closes.
    """
    async with SessionFactory() as session:
        yield session
