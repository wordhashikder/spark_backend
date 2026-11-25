"""Let an installer cover up to 1,000 miles (nationwide businesses).

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-25
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# `op.f` keeps the full name as stored (the naming convention would otherwise prefix it again).
_CONSTRAINT = op.f("ck_installers_coverage_radius_range")


def upgrade() -> None:
    # Only the allowed range changes; no installer's stored radius is touched.
    op.drop_constraint(_CONSTRAINT, "installers", type_="check")
    op.create_check_constraint(
        _CONSTRAINT, "installers", "coverage_radius_miles BETWEEN 1 AND 1000"
    )


def downgrade() -> None:
    # Radii above the old limit cannot be kept under the old rule, so they are capped.
    op.execute(
        "UPDATE installers SET coverage_radius_miles = 100 WHERE coverage_radius_miles > 100"
    )
    op.drop_constraint(_CONSTRAINT, "installers", type_="check")
    op.create_check_constraint(_CONSTRAINT, "installers", "coverage_radius_miles BETWEEN 1 AND 100")
