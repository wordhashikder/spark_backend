"""A per-town closing section: optional heading and Markdown text shown above the footer.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("locations", sa.Column("extra_title", sa.String(length=120), nullable=True))
    op.add_column("locations", sa.Column("extra_body", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("locations", "extra_body")
    op.drop_column("locations", "extra_title")
