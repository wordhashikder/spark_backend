"""Archiving for quote requests and profile enquiries (back office).

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("quote_requests", "installer_enquiries")


def upgrade() -> None:
    # A nullable column with no default: instant on any table size, nothing is rewritten.
    for table in _TABLES:
        op.add_column(table, sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        op.create_index(f"ix_{table}_archived_at", table, ["archived_at"])


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"ix_{table}_archived_at", table_name=table)
        op.drop_column(table, "archived_at")
