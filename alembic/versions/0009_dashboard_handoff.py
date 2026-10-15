"""A one-time token purpose that carries a website sign-in into the Dashboard.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Adding an enum value cannot run inside a transaction block on every server version.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE auth_token_purpose ADD VALUE IF NOT EXISTS 'dashboard_handoff'")


def downgrade() -> None:
    # Postgres cannot drop an enum value; remove the rows so nothing depends on it.
    op.execute("DELETE FROM auth_tokens WHERE purpose = 'dashboard_handoff'")
