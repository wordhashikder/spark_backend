"""Initial schema: accounts, locations, installers, quotes, leads, reviews, billing events.

Revision ID: 0001
Revises:
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Native enum types created implicitly by the tables in upgrade(); dropped explicitly below.
ENUM_TYPES = (
    "accreditation_scheme",
    "auth_token_purpose",
    "charger_followup",
    "charger_location",
    "contact_subject",
    "existing_charger",
    "fuse_box_distance",
    "installation_type",
    "installer_status",
    "lead_status",
    "plan",
    "quote_status",
    "quote_timing",
    "review_status",
    "subscription_status",
    "user_role",
)


def upgrade() -> None:
    op.create_table(
        "contact_messages",
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column(
            "subject",
            sa.Enum(
                "getting_quotes", "joining", "account", "feedback", "other", name="contact_subject"
            ),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_messages")),
    )
    op.create_index(
        "ix_contact_messages_created_at", "contact_messages", ["created_at"], unique=False
    )
    op.create_table(
        "locations",
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("region", sa.String(length=80), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("is_popular", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("popular_rank", sa.Integer(), nullable=True),
        sa.Column("intro", sa.Text(), nullable=True),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_locations")),
        sa.UniqueConstraint("slug", name=op.f("uq_locations_slug")),
    )
    op.create_index(op.f("ix_locations_name"), "locations", ["name"], unique=False)
    op.create_table(
        "stripe_events",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=120), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stripe_events")),
    )
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.Enum("installer", "admin", name="user_role"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_lowercase")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "auth_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum("verify_email", "reset_password", name="auth_token_purpose"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_auth_tokens_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_auth_tokens_token_hash")),
    )
    op.create_index(op.f("ix_auth_tokens_user_id"), "auth_tokens", ["user_id"], unique=False)
    op.create_table(
        "installers",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=140), nullable=False),
        sa.Column("business_name", sa.String(length=120), nullable=False),
        sa.Column("contact_name", sa.String(length=80), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=False),
        sa.Column("tagline", sa.String(length=120), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("website_url", sa.String(length=255), nullable=True),
        sa.Column("company_number", sa.String(length=20), nullable=True),
        sa.Column("base_postcode", sa.String(length=8), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("town", sa.String(length=120), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column(
            "coverage_radius_miles", sa.Integer(), server_default=sa.text("15"), nullable=False
        ),
        sa.Column("years_experience", sa.Integer(), nullable=True),
        sa.Column("logo_url", sa.String(length=500), nullable=True),
        sa.Column("logo_public_id", sa.String(length=255), nullable=True),
        sa.Column(
            "services",
            postgresql.ARRAY(sa.String(length=40)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "areas_covered",
            postgresql.ARRAY(sa.String(length=80)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", "suspended", name="installer_status"),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "plan",
            sa.Enum("free", "pro", "premium", name="plan"),
            server_default="free",
            nullable=False,
        ),
        sa.Column("requested_plan", sa.Enum("free", "pro", "premium", name="plan"), nullable=True),
        sa.Column("is_featured", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
        sa.Column(
            "subscription_status",
            sa.Enum(
                "none", "incomplete", "active", "past_due", "canceled", name="subscription_status"
            ),
            server_default="none",
            nullable=False,
        ),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rating_avg", sa.Numeric(precision=2, scale=1), nullable=True),
        sa.Column("review_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint(
            "services <@ ARRAY['ev_charger_installation', 'domestic_electrical', 'commercial_electrical', 'electrical_repairs', 'solar_battery', 'smart_home', 'eicr_testing']::varchar[]",
            name=op.f("ck_installers_services_known"),
        ),
        sa.CheckConstraint(
            "coverage_radius_miles BETWEEN 1 AND 100",
            name=op.f("ck_installers_coverage_radius_range"),
        ),
        sa.CheckConstraint(
            "rating_avg IS NULL OR rating_avg BETWEEN 1 AND 5",
            name=op.f("ck_installers_rating_range"),
        ),
        sa.CheckConstraint("review_count >= 0", name=op.f("ck_installers_review_count_positive")),
        sa.CheckConstraint(
            "years_experience IS NULL OR years_experience >= 0",
            name=op.f("ck_installers_years_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.id"],
            name=op.f("fk_installers_location_id_locations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_installers_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_installers")),
        sa.UniqueConstraint("slug", name=op.f("uq_installers_slug")),
        sa.UniqueConstraint("stripe_customer_id", name=op.f("uq_installers_stripe_customer_id")),
        sa.UniqueConstraint(
            "stripe_subscription_id", name=op.f("uq_installers_stripe_subscription_id")
        ),
        sa.UniqueConstraint("user_id", name=op.f("uq_installers_user_id")),
    )
    op.create_index(
        "ix_installers_latitude_longitude", "installers", ["latitude", "longitude"], unique=False
    )
    op.create_index(op.f("ix_installers_location_id"), "installers", ["location_id"], unique=False)
    op.create_index(
        "ix_installers_status_is_featured", "installers", ["status", "is_featured"], unique=False
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["replaced_by"],
            ["refresh_tokens.id"],
            name=op.f("fk_refresh_tokens_replaced_by_refresh_tokens"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"], unique=False
    )
    op.create_index(
        op.f("ix_refresh_tokens_replaced_by"), "refresh_tokens", ["replaced_by"], unique=False
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "installer_accreditations",
        sa.Column("installer_id", sa.Uuid(), nullable=False),
        sa.Column(
            "scheme",
            sa.Enum(
                "ozev", "napit", "niceic", "trustmark", "mcs", "elecsa", name="accreditation_scheme"
            ),
            nullable=False,
        ),
        sa.Column("registration_number", sa.String(length=60), nullable=True),
        sa.Column("verified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["installer_id"],
            ["installers.id"],
            name=op.f("fk_installer_accreditations_installer_id_installers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_installer_accreditations")),
        sa.UniqueConstraint(
            "installer_id", "scheme", name="uq_installer_accreditations_installer_scheme"
        ),
    )
    op.create_table(
        "installer_photos",
        sa.Column("installer_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("public_id", sa.String(length=255), nullable=True),
        sa.Column("alt", sa.String(length=160), nullable=True),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["installer_id"],
            ["installers.id"],
            name=op.f("fk_installer_photos_installer_id_installers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_installer_photos")),
    )
    op.create_index(
        op.f("ix_installer_photos_installer_id"), "installer_photos", ["installer_id"], unique=False
    )
    op.create_table(
        "quote_requests",
        sa.Column("reference", sa.String(length=12), nullable=False),
        sa.Column("postcode", sa.String(length=8), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("district", sa.String(length=120), nullable=True),
        sa.Column("region", sa.String(length=120), nullable=True),
        sa.Column(
            "installation_type",
            sa.Enum(
                "new_home",
                "replace_existing",
                "additional",
                "workplace_commercial",
                "not_sure",
                name="installation_type",
            ),
            nullable=False,
        ),
        sa.Column(
            "charger_location",
            sa.Enum(
                "house_wall",
                "garage",
                "detached_garage",
                "post_pedestal",
                "workplace_commercial",
                "other",
                "not_sure",
                name="charger_location",
            ),
            nullable=False,
        ),
        sa.Column(
            "existing_charger",
            sa.Enum("no", "replace", "add_another", name="existing_charger"),
            nullable=False,
        ),
        sa.Column(
            "charger_followup",
            sa.Enum(
                "already_bought",
                "chosen_not_bought",
                "installer_recommend",
                "fit_customer_charger",
                "supply_and_install",
                "recommend_replacement",
                "not_sure",
                name="charger_followup",
            ),
            nullable=False,
        ),
        sa.Column(
            "fuse_box_distance",
            sa.Enum(
                "very_close",
                "inside_house",
                "under_10m",
                "over_10m",
                "not_sure",
                name="fuse_box_distance",
            ),
            nullable=False,
        ),
        sa.Column("vehicle", sa.String(length=120), nullable=True),
        sa.Column(
            "vehicle_undecided", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "timing",
            sa.Enum(
                "asap",
                "within_2_weeks",
                "within_month",
                "one_to_three_months",
                "researching",
                name="quote_timing",
            ),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("first_name", sa.String(length=60), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_installer_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("new", "matched", "unmatched", name="quote_status"),
            server_default="new",
            nullable=False,
        ),
        sa.Column("ip_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["target_installer_id"],
            ["installers.id"],
            name=op.f("fk_quote_requests_target_installer_id_installers"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_requests")),
        sa.UniqueConstraint("reference", name=op.f("uq_quote_requests_reference")),
    )
    op.create_index("ix_quote_requests_created_at", "quote_requests", ["created_at"], unique=False)
    op.create_index(op.f("ix_quote_requests_ip_hash"), "quote_requests", ["ip_hash"], unique=False)
    op.create_index(op.f("ix_quote_requests_status"), "quote_requests", ["status"], unique=False)
    op.create_index(
        op.f("ix_quote_requests_target_installer_id"),
        "quote_requests",
        ["target_installer_id"],
        unique=False,
    )
    op.create_table(
        "quote_matches",
        sa.Column("quote_request_id", sa.Uuid(), nullable=False),
        sa.Column("installer_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("sent", "viewed", "contacted", "won", "lost", name="lead_status"),
            server_default="sent",
            nullable=False,
        ),
        sa.Column("review_invited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["installer_id"],
            ["installers.id"],
            name=op.f("fk_quote_matches_installer_id_installers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["quote_request_id"],
            ["quote_requests.id"],
            name=op.f("fk_quote_matches_quote_request_id_quote_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_matches")),
        sa.UniqueConstraint(
            "quote_request_id", "installer_id", name="uq_quote_matches_quote_installer"
        ),
    )
    op.create_index(
        "ix_quote_matches_installer_id_created_at",
        "quote_matches",
        ["installer_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "reviews",
        sa.Column("installer_id", sa.Uuid(), nullable=False),
        sa.Column("quote_match_id", sa.Uuid(), nullable=True),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("title", sa.String(length=80), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author_name", sa.String(length=60), nullable=False),
        sa.Column("author_location", sa.String(length=60), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "published", "rejected", name="review_status"),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
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
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name=op.f("ck_reviews_rating_range")),
        sa.ForeignKeyConstraint(
            ["installer_id"],
            ["installers.id"],
            name=op.f("fk_reviews_installer_id_installers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["quote_match_id"],
            ["quote_matches.id"],
            name=op.f("fk_reviews_quote_match_id_quote_matches"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviews")),
        sa.UniqueConstraint("quote_match_id", name=op.f("uq_reviews_quote_match_id")),
    )
    op.create_index(
        "ix_reviews_installer_id_status_created_at",
        "reviews",
        ["installer_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_reviews_status_created_at", "reviews", ["status", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_reviews_status_created_at", table_name="reviews")
    op.drop_index("ix_reviews_installer_id_status_created_at", table_name="reviews")
    op.drop_table("reviews")
    op.drop_index("ix_quote_matches_installer_id_created_at", table_name="quote_matches")
    op.drop_table("quote_matches")
    op.drop_index(op.f("ix_quote_requests_target_installer_id"), table_name="quote_requests")
    op.drop_index(op.f("ix_quote_requests_status"), table_name="quote_requests")
    op.drop_index(op.f("ix_quote_requests_ip_hash"), table_name="quote_requests")
    op.drop_index("ix_quote_requests_created_at", table_name="quote_requests")
    op.drop_table("quote_requests")
    op.drop_index(op.f("ix_installer_photos_installer_id"), table_name="installer_photos")
    op.drop_table("installer_photos")
    op.drop_table("installer_accreditations")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_replaced_by"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("ix_installers_status_is_featured", table_name="installers")
    op.drop_index(op.f("ix_installers_location_id"), table_name="installers")
    op.drop_index("ix_installers_latitude_longitude", table_name="installers")
    op.drop_table("installers")
    op.drop_index(op.f("ix_auth_tokens_user_id"), table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_table("users")
    op.drop_table("stripe_events")
    op.drop_index(op.f("ix_locations_name"), table_name="locations")
    op.drop_table("locations")
    op.drop_index("ix_contact_messages_created_at", table_name="contact_messages")
    op.drop_table("contact_messages")
    for enum_type in ENUM_TYPES:
        sa.Enum(name=enum_type).drop(op.get_bind(), checkfirst=True)
