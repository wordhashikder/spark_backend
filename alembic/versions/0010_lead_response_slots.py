"""Record when an installer first responded to a lead.

A request is now sent to every eligible installer, but only the first few to respond
(Settings › Lead matching) may quote. `responded_at` is that first response, so the limit
can be checked and enforced cheaply and without races.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "quote_matches", sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Leads answered before this change keep their place: the installer's first message or
    # quote is the moment they responded.
    op.execute(
        """
        UPDATE quote_matches AS m
        SET responded_at = r.first_at
        FROM (
            SELECT c.quote_match_id AS match_id, MIN(x.at) AS first_at
            FROM conversations AS c
            JOIN (
                SELECT conversation_id, created_at AS at
                FROM conversation_messages WHERE sender = 'installer'
                UNION ALL
                SELECT conversation_id, created_at AS at FROM offers
            ) AS x ON x.conversation_id = c.id
            WHERE c.quote_match_id IS NOT NULL
            GROUP BY c.quote_match_id
        ) AS r
        WHERE m.id = r.match_id
        """
    )


def downgrade() -> None:
    op.drop_column("quote_matches", "responded_at")
