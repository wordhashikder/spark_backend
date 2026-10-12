"""Back office: staff roles and the role matrix, platform settings, managed page content
with its edit history, and draft/published location pages with an H1 override.

Existing admin accounts become owners.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

staff_role = postgresql.ENUM(
    "owner", "manager", "editor", "support", name="staff_role", create_type=False
)


def _edited_document(name: str, key_type: sa.types.TypeEngine) -> None:
    op.create_table(
        name,
        sa.Column("key", key_type, nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name=op.f(f"fk_{name}_updated_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("key", name=op.f(f"pk_{name}")),
    )


def upgrade() -> None:
    # Adding an enum value cannot run inside a transaction block on every server version.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE auth_token_purpose ADD VALUE IF NOT EXISTS 'staff_invite'")

    staff_role.create(op.get_bind(), checkfirst=True)
    op.add_column("users", sa.Column("staff_role", staff_role, nullable=True))
    op.add_column("users", sa.Column("full_name", sa.String(length=80), nullable=True))
    op.execute("UPDATE users SET staff_role = 'owner' WHERE role = 'admin'")
    op.create_check_constraint(
        "staff_role_for_admins", "users", "(role = 'admin') = (staff_role IS NOT NULL)"
    )

    op.create_table(
        "role_permissions",
        sa.Column("staff_role", staff_role, nullable=False),
        sa.Column("module", sa.String(length=40), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("staff_role", "module", name=op.f("pk_role_permissions")),
    )
    _edited_document("platform_settings", sa.String(length=60))
    _edited_document("site_content", sa.String(length=60))
    op.create_table(
        "site_content_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_site_content_revisions_author_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_site_content_revisions")),
    )
    op.create_index(
        "ix_site_content_revisions_key_created_at",
        "site_content_revisions",
        ["key", "created_at"],
    )

    op.add_column("locations", sa.Column("h1_heading", sa.String(length=120), nullable=True))
    op.add_column(
        "locations",
        sa.Column("is_published", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("locations", "is_published")
    op.drop_column("locations", "h1_heading")
    op.drop_index("ix_site_content_revisions_key_created_at", table_name="site_content_revisions")
    op.drop_table("site_content_revisions")
    op.drop_table("site_content")
    op.drop_table("platform_settings")
    op.drop_table("role_permissions")
    op.drop_constraint("staff_role_for_admins", "users", type_="check")
    op.drop_column("users", "full_name")
    op.drop_column("users", "staff_role")
    staff_role.drop(op.get_bind(), checkfirst=True)
    # Pending staff invitations cannot outlive their purpose; the enum value itself stays
    # (PostgreSQL cannot drop a value from an enum type) and is harmless.
    op.execute("DELETE FROM auth_tokens WHERE purpose = 'staff_invite'")
