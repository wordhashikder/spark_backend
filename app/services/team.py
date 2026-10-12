"""The PickASparky team: who may do what in the back office, invitations and the matrix.

Team members are `admin` accounts with a staff role. They join by invitation: the invite
creates the account (unverified, with an unusable password) and emails a single-use link;
accepting it sets the password and verifies the address.
"""

import secrets
import uuid
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.enums import AuthTokenPurpose, Role, StaffRole
from app.core.exceptions import (
    ConflictError,
    FieldValidationError,
    ForbiddenError,
    InvalidTokenError,
    NotFoundError,
)
from app.core.permissions import DEFAULT_ACCESS, MODULE_KEYS, MODULES, ROLE_LABELS
from app.models import AuthToken, RolePermission, User
from app.models.base import utcnow
from app.schemas.team import (
    InviteCreate,
    ModuleInfo,
    RoleInfo,
    RoleMatrix,
    TeamMember,
    TeamMemberUpdate,
)
from app.services import email as emails
from app.services.access import access_for
from app.services.auth import _consume_auth_token, _issue_auth_token
from app.services.email import Email

INVITE_LIFETIME = timedelta(days=7)


class OwnersOnlyError(ForbiddenError):
    code = "owners_only"
    message = "Only an owner can do this."


class LastOwnerError(ConflictError):
    code = "last_owner"
    message = "The team must keep at least one active owner."


# ---- Permissions -------------------------------------------------------------------------


async def matrix(session: AsyncSession) -> RoleMatrix:
    return RoleMatrix(
        roles=[
            RoleInfo(
                role=role,
                label=ROLE_LABELS[role][0],
                description=ROLE_LABELS[role][1],
                editable=role is not StaffRole.OWNER,
            )
            for role in StaffRole
        ],
        modules=[
            ModuleInfo(key=module.key, label=module.label, description=module.description)
            for module in MODULES
        ],
        access={
            role: sorted(await access_for(session, role), key=MODULE_KEYS.index)
            for role in StaffRole
        },
    )


async def update_matrix(
    session: AsyncSession, actor: User, access: dict[StaffRole, list[str]]
) -> RoleMatrix:
    """Store the cells that differ from the defaults; owners always keep everything."""
    _require_owner(actor)
    for role, modules in access.items():
        if role is StaffRole.OWNER:
            continue
        await session.execute(delete(RolePermission).where(RolePermission.staff_role == role))
        wanted = set(modules)
        for module in MODULE_KEYS:
            allowed = module in wanted
            if allowed != (module in DEFAULT_ACCESS[role]):
                session.add(RolePermission(staff_role=role, module=module, allowed=allowed))
    await session.commit()
    return await matrix(session)


# ---- Team --------------------------------------------------------------------------------


def _member(user: User, actor: User) -> TeamMember:
    if user.staff_role is None:  # pragma: no cover - guaranteed by a check constraint
        raise RuntimeError("Admin account without a staff role")
    return TeamMember(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        staff_role=user.staff_role,
        is_active=user.is_active,
        joined=user.email_verified_at is not None,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        is_you=user.id == actor.id,
    )


async def list_members(session: AsyncSession, actor: User) -> list[TeamMember]:
    users = await session.scalars(
        select(User).where(User.role == Role.ADMIN).order_by(User.created_at, User.email)
    )
    return [_member(user, actor) for user in users]


async def invite(
    session: AsyncSession, actor: User, data: InviteCreate
) -> tuple[TeamMember, list[Email]]:
    if data.staff_role is StaffRole.OWNER:
        _require_owner(actor)
    existing = await session.scalar(select(User).where(User.email == data.email))
    if existing is not None:
        if existing.role is not Role.ADMIN or existing.email_verified_at is not None:
            raise FieldValidationError({"email": "This email address already has an account."})
        # Not accepted yet: refresh the invitation with the new details.
        user = existing
        user.staff_role = data.staff_role
        user.full_name = data.full_name or user.full_name
    else:
        user = User(
            email=data.email,
            # Unusable until the invitation is accepted.
            password_hash=await security.hash_password(secrets.token_urlsafe(32)),
            role=Role.ADMIN,
            staff_role=data.staff_role,
            full_name=data.full_name,
        )
        session.add(user)
        await session.flush()
    token = await _issue_auth_token(session, user, AuthTokenPurpose.STAFF_INVITE, INVITE_LIFETIME)
    await session.commit()
    return _member(user, actor), [emails.staff_invite(user, actor, token)]


async def resend_invite(
    session: AsyncSession, actor: User, member_id: uuid.UUID
) -> tuple[TeamMember, list[Email]]:
    user = await _get(session, member_id)
    if user.email_verified_at is not None:
        raise ConflictError("This person has already joined.", code="already_joined")
    if user.staff_role is StaffRole.OWNER:
        _require_owner(actor)
    token = await _issue_auth_token(session, user, AuthTokenPurpose.STAFF_INVITE, INVITE_LIFETIME)
    await session.commit()
    return _member(user, actor), [emails.staff_invite(user, actor, token)]


async def update_member(
    session: AsyncSession, actor: User, member_id: uuid.UUID, data: TeamMemberUpdate
) -> TeamMember:
    user = await _get(session, member_id, lock=True)
    changes_owner = StaffRole.OWNER in (user.staff_role, data.staff_role)
    if changes_owner and ("staff_role" in data.model_fields_set or data.is_active is not None):
        _require_owner(actor)
    losing_owner = user.staff_role is StaffRole.OWNER and (
        (data.staff_role is not None and data.staff_role is not StaffRole.OWNER)
        or data.is_active is False
    )
    if losing_owner and await _active_owner_count(session) <= 1:
        raise LastOwnerError
    if data.is_active is False and user.id == actor.id:
        raise ConflictError(
            "You cannot deactivate your own account.", code="cannot_deactivate_self"
        )

    if "full_name" in data.model_fields_set:
        user.full_name = data.full_name
    if data.staff_role is not None:
        user.staff_role = data.staff_role
    if data.is_active is not None:
        user.is_active = data.is_active
    await session.commit()
    return _member(user, actor)


async def remove_invite(session: AsyncSession, actor: User, member_id: uuid.UUID) -> None:
    """Withdraw an invitation that has not been accepted (joined members are deactivated)."""
    user = await _get(session, member_id)
    if user.email_verified_at is not None:
        raise ConflictError(
            "This person has joined; deactivate the account instead.", code="already_joined"
        )
    if user.staff_role is StaffRole.OWNER:
        _require_owner(actor)
    await session.delete(user)
    await session.commit()


# ---- Accepting an invitation -------------------------------------------------------------


async def preview_invite(session: AsyncSession, token: str) -> User:
    """The invitee, without using up the token (the accept page shows who is joining)."""
    stored = await session.scalar(
        select(AuthToken).where(
            AuthToken.token_hash == security.hash_token(token),
            AuthToken.purpose == AuthTokenPurpose.STAFF_INVITE,
            AuthToken.used_at.is_(None),
            AuthToken.expires_at > utcnow(),
        )
    )
    user = await session.get(User, stored.user_id) if stored else None
    if user is None or not user.is_active:
        raise InvalidTokenError
    return user


async def accept_invite(
    session: AsyncSession, token: str, password: str, full_name: str | None
) -> User:
    user = await _consume_auth_token(session, token, AuthTokenPurpose.STAFF_INVITE)
    now = utcnow()
    user.password_hash = await security.hash_password(password)
    user.email_verified_at = user.email_verified_at or now
    if full_name:
        user.full_name = full_name
    await session.commit()
    return user


# ---- Helpers -----------------------------------------------------------------------------


def _require_owner(actor: User) -> None:
    if actor.staff_role is not StaffRole.OWNER:
        raise OwnersOnlyError


async def _get(session: AsyncSession, member_id: uuid.UUID, *, lock: bool = False) -> User:
    statement = select(User).where(User.id == member_id, User.role == Role.ADMIN)
    if lock:
        statement = statement.with_for_update()
    user = await session.scalar(statement)
    if user is None:
        raise NotFoundError("Team member not found.")
    return user


async def _active_owner_count(session: AsyncSession) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.role == Role.ADMIN,
                User.staff_role == StaffRole.OWNER,
                User.is_active,
                User.email_verified_at.is_not(None),
            )
        )
        or 0
    )
