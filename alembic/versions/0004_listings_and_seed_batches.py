"""Free basic listings (installers without an account), seed batches, location SEO fields.

- `installers.user_id` becomes optional: PickASparky can list a business before it has an
  account. Deleting an account now leaves its listing unclaimed instead of deleting it.
- `installers.source`, `contact_email`, `address`, `claimed_at` describe those listings.
- `seed_batches` records which content batches the seed has applied, so each is inserted
  once and later admin edits or deletions are never undone.
- `locations.seo_title` / `seo_description`: optional search snippet overrides.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

installer_source = postgresql.ENUM(
    "registered", "imported", name="installer_source", create_type=False
)


def upgrade() -> None:
    op.create_table(
        "seed_batches",
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_seed_batches")),
    )

    installer_source.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "installers",
        sa.Column("source", installer_source, server_default="registered", nullable=False),
    )
    op.add_column("installers", sa.Column("contact_email", sa.String(length=254), nullable=True))
    op.add_column("installers", sa.Column("address", sa.String(length=255), nullable=True))
    op.add_column("installers", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("installers", "user_id", existing_type=sa.UUID(), nullable=True)
    op.drop_constraint(op.f("fk_installers_user_id_users"), "installers", type_="foreignkey")
    op.create_foreign_key(
        op.f("fk_installers_user_id_users"),
        "installers",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("locations", sa.Column("seo_title", sa.String(length=70), nullable=True))
    op.add_column("locations", sa.Column("seo_description", sa.String(length=160), nullable=True))


def downgrade() -> None:
    op.drop_column("locations", "seo_description")
    op.drop_column("locations", "seo_title")

    # Listings without an account cannot exist in the older schema.
    op.execute("DELETE FROM installers WHERE user_id IS NULL")
    op.drop_constraint(op.f("fk_installers_user_id_users"), "installers", type_="foreignkey")
    op.create_foreign_key(
        op.f("fk_installers_user_id_users"),
        "installers",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("installers", "user_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("installers", "claimed_at")
    op.drop_column("installers", "address")
    op.drop_column("installers", "contact_email")
    op.drop_column("installers", "source")
    installer_source.drop(op.get_bind(), checkfirst=True)

    op.drop_table("seed_batches")
