"""Which back-office modules a team member's staff role may use (see `core/permissions.py`)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import StaffRole
from app.core.permissions import DEFAULT_ACCESS, MODULE_KEYS
from app.models import RolePermission


async def access_for(session: AsyncSession, staff_role: StaffRole | None) -> frozenset[str]:
    """The modules a staff role may use: the defaults with the owners' changes applied."""
    if staff_role is None:
        return frozenset()
    if staff_role is StaffRole.OWNER:
        return frozenset(MODULE_KEYS)
    allowed = set(DEFAULT_ACCESS[staff_role])
    rows = await session.scalars(
        select(RolePermission).where(RolePermission.staff_role == staff_role)
    )
    for row in rows:
        if row.allowed:
            allowed.add(row.module)
        else:
            allowed.discard(row.module)
    return frozenset(allowed & set(MODULE_KEYS))
