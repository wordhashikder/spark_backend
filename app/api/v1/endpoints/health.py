"""Liveness and readiness probes."""

import logging

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import SessionDep
from app.core.exceptions import ServiceUnavailableError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", summary="Readiness probe (checks the database)")
async def ready(session: SessionDep) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("Readiness check failed: %s", exc.__class__.__name__)
        raise ServiceUnavailableError("The database is not reachable.") from exc
    return {"status": "ok"}
