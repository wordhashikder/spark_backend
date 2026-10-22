"""Dynamic membership plans, prices, invoices and subscription state.

Plans used to be a fixed enum with their prices in environment variables. They are now
rows the Dashboard manages: `plans` (what each tier allows), `plan_prices` (recurring
Stripe prices) and, for the payment pipeline, `billing_invoices` (payment history) and
`billing_activity` (plan changes). Installers reference a plan by key. The three existing
plans are seeded with the capabilities they always had; their Stripe prices are created
from the Dashboard (or on first checkout).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-22
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLAN_ENUM_VALUES = ("free", "pro", "premium")

_SEED_PLANS = [
    {
        "key": "free",
        "name": "Free",
        "features": [
            "Get listed on PickASparky",
            "Show your profile on the site",
            "Appear in search results",
            "Basic business information",
        ],
        "is_default": True,
        "is_popular": False,
        "sort_rank": 0,
        "receives_leads": False,
        "accepts_direct_quotes": False,
        "full_public_profile": False,
        "public_service_limit": 2,
        "max_gallery_photos": 0,
        "price_pence": None,
    },
    {
        "key": "pro",
        "name": "Pro",
        "features": [
            "Featured listing",
            "Appear at the top of the list",
            "Receive and respond to enquiries",
            "Show all your services and accreditations",
        ],
        "is_default": False,
        "is_popular": True,
        "sort_rank": 1,
        "receives_leads": True,
        "accepts_direct_quotes": True,
        "full_public_profile": True,
        "public_service_limit": None,
        "max_gallery_photos": 12,
        "price_pence": 2900,
    },
    {
        "key": "premium",
        "name": "Premium",
        "features": [
            "Everything in Pro",
            "Premium support",
            "Priority visibility",
            "Early access to new features",
        ],
        "is_default": False,
        "is_popular": False,
        "sort_rank": 2,
        "receives_leads": True,
        "accepts_direct_quotes": True,
        "full_public_profile": True,
        "public_service_limit": None,
        "max_gallery_photos": 24,
        "price_pence": 4900,
    },
]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    plans = op.create_table(
        "plans",
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("tagline", sa.String(200), nullable=True),
        sa.Column(
            "features",
            postgresql.ARRAY(sa.String(200)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("is_popular", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("sort_rank", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("receives_leads", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("accepts_direct_quotes", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("full_public_profile", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("public_service_limit", sa.Integer(), nullable=True),
        sa.Column("max_gallery_photos", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("stripe_product_id", sa.String(255), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("key", name="pk_plans"),
        sa.UniqueConstraint("stripe_product_id", name="uq_plans_stripe_product_id"),
        sa.CheckConstraint("sort_rank >= 0", name="ck_plans_sort_rank_range"),
        sa.CheckConstraint("max_gallery_photos >= 0", name="ck_plans_max_gallery_photos_range"),
        sa.CheckConstraint(
            "public_service_limit IS NULL OR public_service_limit >= 1",
            name="ck_plans_public_service_limit_range",
        ),
    )
    op.create_index(
        "uq_plans_single_default",
        "plans",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    plan_prices = op.create_table(
        "plan_prices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_key", sa.String(40), nullable=False),
        sa.Column("interval", sa.String(10), server_default="month", nullable=False),
        sa.Column("amount_pence", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), server_default="gbp", nullable=False),
        sa.Column("stripe_price_id", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_plan_prices"),
        sa.ForeignKeyConstraint(
            ["plan_key"], ["plans.key"], name="fk_plan_prices_plan_key_plans", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("stripe_price_id", name="uq_plan_prices_stripe_price_id"),
        sa.CheckConstraint("amount_pence > 0", name="ck_plan_prices_amount_positive"),
        sa.CheckConstraint("interval IN ('month', 'year')", name="ck_plan_prices_interval_known"),
    )
    op.create_index("ix_plan_prices_plan_key", "plan_prices", ["plan_key"])
    op.create_index(
        "uq_plan_prices_one_active",
        "plan_prices",
        ["plan_key", "interval"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.bulk_insert(
        plans,
        [
            {name: value for name, value in seed.items() if name != "price_pence"}
            for seed in _SEED_PLANS
        ],
    )
    op.bulk_insert(
        plan_prices,
        [
            {
                "id": uuid.uuid4(),
                "plan_key": seed["key"],
                "amount_pence": seed["price_pence"],
            }
            for seed in _SEED_PLANS
            if seed["price_pence"] is not None
        ],
    )

    # Installers: the pg enum becomes a key into `plans`.
    op.execute("ALTER TABLE installers ALTER COLUMN plan DROP DEFAULT")
    op.execute("ALTER TABLE installers ALTER COLUMN plan TYPE VARCHAR(40) USING plan::text")
    op.execute("ALTER TABLE installers ALTER COLUMN plan SET DEFAULT 'free'")
    op.execute(
        "ALTER TABLE installers ALTER COLUMN requested_plan TYPE VARCHAR(40) "
        "USING requested_plan::text"
    )
    op.execute("DROP TYPE plan")
    op.create_foreign_key("fk_installers_plan_plans", "installers", "plans", ["plan"], ["key"])
    op.create_foreign_key(
        "fk_installers_requested_plan_plans", "installers", "plans", ["requested_plan"], ["key"]
    )

    op.add_column(
        "installers",
        sa.Column(
            "cancel_at_period_end", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.add_column("installers", sa.Column("pending_plan", sa.String(40), nullable=True))
    op.add_column("installers", sa.Column("stripe_schedule_id", sa.String(255), nullable=True))
    op.add_column("installers", sa.Column("plan_price_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_installers_pending_plan_plans", "installers", "plans", ["pending_plan"], ["key"]
    )
    op.create_foreign_key(
        "fk_installers_plan_price_id_plan_prices",
        "installers",
        "plan_prices",
        ["plan_price_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "billing_invoices",
        sa.Column("id", sa.String(255), nullable=False),
        sa.Column("installer_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(80), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("description", sa.String(300), nullable=True),
        sa.Column("plan_name", sa.String(60), nullable=True),
        sa.Column("amount_due_pence", sa.Integer(), nullable=False),
        sa.Column("amount_paid_pence", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("billing_reason", sa.String(40), nullable=True),
        sa.Column("hosted_invoice_url", sa.Text(), nullable=True),
        sa.Column("invoice_pdf_url", sa.Text(), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name="pk_billing_invoices"),
        sa.ForeignKeyConstraint(
            ["installer_id"],
            ["installers.id"],
            name="fk_billing_invoices_installer_id_installers",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_billing_invoices_installer_issued", "billing_invoices", ["installer_id", "issued_at"]
    )

    op.create_table(
        "billing_activity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("installer_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("message", sa.String(300), nullable=False),
        sa.Column("from_plan", sa.String(40), nullable=True),
        sa.Column("to_plan", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_billing_activity"),
        sa.ForeignKeyConstraint(
            ["installer_id"],
            ["installers.id"],
            name="fk_billing_activity_installer_id_installers",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_billing_activity_installer_created", "billing_activity", ["installer_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("billing_activity")
    op.drop_table("billing_invoices")

    op.drop_constraint("fk_installers_plan_price_id_plan_prices", "installers", type_="foreignkey")
    op.drop_constraint("fk_installers_pending_plan_plans", "installers", type_="foreignkey")
    op.drop_constraint("fk_installers_requested_plan_plans", "installers", type_="foreignkey")
    op.drop_constraint("fk_installers_plan_plans", "installers", type_="foreignkey")
    for column in ("plan_price_id", "stripe_schedule_id", "pending_plan", "cancel_at_period_end"):
        op.drop_column("installers", column)

    values = ", ".join(f"'{value}'" for value in _PLAN_ENUM_VALUES)
    op.execute(f"CREATE TYPE plan AS ENUM ({values})")
    # Plans created in the Dashboard have no equivalent in the old enum: they become Free.
    for column in ("plan", "requested_plan"):
        op.execute(
            f"UPDATE installers SET {column} = 'free' "
            f"WHERE {column} IS NOT NULL AND {column} NOT IN ({values})"
        )
    op.execute("ALTER TABLE installers ALTER COLUMN plan DROP DEFAULT")
    op.execute("ALTER TABLE installers ALTER COLUMN plan TYPE plan USING plan::plan")
    op.execute("ALTER TABLE installers ALTER COLUMN plan SET DEFAULT 'free'")
    op.execute(
        "ALTER TABLE installers ALTER COLUMN requested_plan TYPE plan USING requested_plan::plan"
    )

    op.drop_table("plan_prices")
    op.drop_table("plans")
