"""Curated location directory: each location's column and position.

Replaces the `is_popular` / `popular_rank` pair, which only fed the "Popular Locations"
column, with one column-and-position slot per location covering all four columns.
The seed (`python -m app.cli seed-locations`, run on every start-up) fills in the layout.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

directory_column = postgresql.ENUM(
    "nearby", "popular", "more_in_area", "other", name="directory_column", create_type=False
)


def upgrade() -> None:
    directory_column.create(op.get_bind(), checkfirst=True)
    op.add_column("locations", sa.Column("directory_column", directory_column, nullable=True))
    op.add_column("locations", sa.Column("directory_position", sa.SmallInteger(), nullable=True))

    # Keep today's popular picks, in their order, until the seed applies the full layout.
    op.execute(
        """
        UPDATE locations AS l
        SET directory_column = 'popular', directory_position = ranked.position
        FROM (
            SELECT id, row_number() OVER (ORDER BY popular_rank NULLS LAST, name) AS position
            FROM locations
            WHERE is_popular
        ) AS ranked
        WHERE l.id = ranked.id
        """
    )
    op.create_unique_constraint(
        "uq_locations_directory_slot",
        "locations",
        ["directory_column", "directory_position"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.drop_column("locations", "popular_rank")
    op.drop_column("locations", "is_popular")


def downgrade() -> None:
    op.add_column(
        "locations",
        sa.Column("is_popular", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("locations", sa.Column("popular_rank", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE locations
        SET is_popular = true, popular_rank = directory_position
        WHERE directory_column = 'popular'
        """
    )
    op.drop_constraint("uq_locations_directory_slot", "locations", type_="unique")
    op.drop_column("locations", "directory_position")
    op.drop_column("locations", "directory_column")
    directory_column.drop(op.get_bind(), checkfirst=True)
