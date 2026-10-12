"""The PickASparky team (admin accounts), invitations and the role matrix."""

import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, field_validator, model_validator

from app.core.enums import StaffRole
from app.core.permissions import MODULE_KEYS
from app.schemas.common import Email, OpaqueToken, Password, blank_as_none, text

FullName = Annotated[Annotated[str, text(2, 80)] | None, blank_as_none]


class TeamMember(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    staff_role: StaffRole
    is_active: bool
    # False until the invitation has been accepted (a password has been set).
    joined: bool
    last_login_at: datetime | None
    created_at: datetime
    is_you: bool


class InviteCreate(BaseModel):
    email: Email
    full_name: FullName = None
    staff_role: StaffRole


class TeamMemberUpdate(BaseModel):
    full_name: FullName = None
    staff_role: StaffRole | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _something_to_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        return self


class ModuleInfo(BaseModel):
    key: str
    label: str
    description: str


class RoleInfo(BaseModel):
    role: StaffRole
    label: str
    description: str
    editable: bool


class RoleMatrix(BaseModel):
    roles: list[RoleInfo]
    modules: list[ModuleInfo]
    # role -> the modules it may use
    access: dict[StaffRole, list[str]]


class RoleMatrixUpdate(BaseModel):
    access: dict[StaffRole, list[str]]

    @field_validator("access")
    @classmethod
    def _known_modules(cls, value: dict[StaffRole, list[str]]) -> dict[StaffRole, list[str]]:
        for modules in value.values():
            unknown = set(modules) - set(MODULE_KEYS)
            if unknown:
                raise ValueError(f"Unknown modules: {', '.join(sorted(unknown))}.")
        return value


class InvitePreview(BaseModel):
    email: str
    full_name: str | None
    staff_role: StaffRole


class InviteAccept(BaseModel):
    token: OpaqueToken
    password: Password
    full_name: FullName = None
