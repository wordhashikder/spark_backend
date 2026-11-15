"""A quote status for requests received while the postcode lookup was unavailable.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Adding an enum value cannot run inside a transaction block on every server version.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE quote_status ADD VALUE IF NOT EXISTS 'pending_location'")


def downgrade() -> None:
    # Postgres cannot drop an enum value; put the requests back to a state that value-less
    # code understands (they would have been matched or left for the team anyway).
    op.execute("UPDATE quote_requests SET status = 'unmatched' WHERE status = 'pending_location'")
