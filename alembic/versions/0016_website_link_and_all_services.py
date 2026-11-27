"""Website link as a plan setting; every plan shows all services.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "plans",
        sa.Column("shows_website_link", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    # Starts where the paid plans already are: a plan with the full public profile (Pro and
    # Premium) shows the link, Free does not. The team can change it per plan afterwards.
    op.execute("UPDATE plans SET shows_website_link = full_public_profile")
    # Every plan now shows all of an installer's services (empty = no limit).
    op.execute("UPDATE plans SET public_service_limit = NULL")


def downgrade() -> None:
    op.drop_column("plans", "shows_website_link")
    # The former per-plan service limits are not restored: set them again in Dashboard > Plans.