"""Customers and passwordless sign-in: a customer record per email address, emailed magic
links and the sessions they start. Existing quote requests are attached to customers.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("first_name", sa.String(length=60), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_customers_email_lowercase")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
        sa.UniqueConstraint("email", name=op.f("uq_customers_email")),
    )
    op.create_table(
        "customer_login_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_customer_login_links_customer_id_customers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_login_links")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_customer_login_links_token_hash")),
    )
    op.create_index(
        op.f("ix_customer_login_links_customer_id"), "customer_login_links", ["customer_id"]
    )
    op.create_table(
        "customer_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_customer_sessions_customer_id_customers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_customer_sessions_token_hash")),
    )
    op.create_index(op.f("ix_customer_sessions_customer_id"), "customer_sessions", ["customer_id"])

    op.add_column("quote_requests", sa.Column("customer_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_quote_requests_customer_id_customers"),
        "quote_requests",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_quote_requests_customer_id"), "quote_requests", ["customer_id"])

    # Existing requests: one customer per email address (the most recent name and phone).
    op.execute(
        """
        INSERT INTO customers (id, email, first_name, phone)
        SELECT DISTINCT ON (lower(email)) gen_random_uuid(), lower(email), first_name, phone
        FROM quote_requests
        ORDER BY lower(email), created_at DESC
        """
    )
    op.execute(
        "UPDATE quote_requests q SET customer_id = c.id FROM customers c "
        "WHERE c.email = lower(q.email)"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_quote_requests_customer_id"), table_name="quote_requests")
    op.drop_constraint(
        op.f("fk_quote_requests_customer_id_customers"), "quote_requests", type_="foreignkey"
    )
    op.drop_column("quote_requests", "customer_id")
    op.drop_table("customer_sessions")
    op.drop_table("customer_login_links")
    op.drop_table("customers")
