"""Dashboard-managed accreditation schemes (with SELECT) and reusable website pages.

The six fixed schemes of the old `accreditation_scheme` enum become rows of a new
`accreditation_schemes` table (plus SELECT), so the team can add, rename and switch them off.
Installers' accreditations keep their values: the column changes from the enum to the
scheme's `key`. `site_pages` holds the pages built in Website content > Pages.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_KEYS = ("ozev", "napit", "niceic", "trustmark", "mcs", "elecsa")
# (key, name, badge, card title, card text); the wording of the first six is the profile
# cards' existing text, and the badges come from the client's accreditation-card design.
_SCHEMES = (
    (
        "niceic",
        "NICEIC",
        "Recognised Standard",
        "NICEIC Approved",
        "Assessed by NICEIC against the requirements of BS 7671 (the IET Wiring Regulations), "
        "ensuring safe and compliant electrical work.",
    ),
    (
        "napit",
        "NAPIT",
        "Competent Person Scheme",
        "NAPIT Registered",
        "Registered with NAPIT, a government-authorised Competent Person Scheme operator.",
    ),
    (
        "trustmark",
        "TrustMark",
        "Gov. Endorsed",
        "TrustMark Registered",
        "Registered with TrustMark, the UK Government-endorsed quality scheme for reliable, "
        "vetted tradespeople in and around the home.",
    ),
    (
        "elecsa",
        "ELECSA",
        "Competent Person Scheme",
        "ELECSA Registered",
        "Registered with ELECSA, a Competent Person Scheme for electrical work, giving "
        "confidence that work meets UK building and safety regulations.",
    ),
    (
        "ozev",
        "OZEV",
        None,
        "OZEV Approved",
        "Authorised to install EV charge points under the UK government's OZEV grant schemes.",
    ),
    (
        "mcs",
        "MCS",
        None,
        "MCS Certified",
        "Certified under MCS for small-scale renewable and low-carbon technologies.",
    ),
    (
        "select",
        "SELECT",
        None,
        "SELECT Registered",
        "Registered with SELECT, the trade association for Scotland's electrical contracting "
        "industry.",
    ),
)


def upgrade() -> None:
    schemes = op.create_table(
        "accreditation_schemes",
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("badge", sa.String(40), nullable=True),
        sa.Column("card_title", sa.String(80), nullable=False),
        sa.Column("card_text", sa.String(400), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("key", name="pk_accreditation_schemes"),
    )
    op.bulk_insert(
        schemes,
        [
            {
                "key": key,
                "name": name,
                "badge": badge,
                "card_title": title,
                "card_text": body,
                "position": index * 10,
            }
            for index, (key, name, badge, title, body) in enumerate(_SCHEMES)
        ],
    )

    # Installers keep what they listed: the enum value becomes the scheme's key.
    op.alter_column(
        "installer_accreditations",
        "scheme",
        type_=sa.String(40),
        existing_nullable=False,
        postgresql_using="scheme::text",
    )
    op.execute("DROP TYPE accreditation_scheme")
    op.create_foreign_key(
        "fk_installer_accreditations_scheme_accreditation_schemes",
        "installer_accreditations",
        "accreditation_schemes",
        ["scheme"],
        ["key"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "site_pages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(200), nullable=False),
        sa.Column("parent_path", sa.String(200), nullable=True),
        sa.Column(
            "previous_paths",
            postgresql.ARRAY(sa.String(200)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("eyebrow", sa.String(60), nullable=True),
        sa.Column("intro", sa.Text(), nullable=True),
        sa.Column("hero_image_url", sa.String(500), nullable=True),
        sa.Column("hero_image_alt", sa.String(160), nullable=True),
        sa.Column(
            "sections", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("faq", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("seo_title", sa.String(70), nullable=True),
        sa.Column("seo_description", sa.String(160), nullable=True),
        sa.Column("is_published", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("scheme_key", sa.String(40), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["scheme_key"],
            ["accreditation_schemes.key"],
            name="fk_site_pages_scheme_key_accreditation_schemes",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_site_pages"),
        sa.UniqueConstraint("path", name="uq_site_pages_path"),
        sa.UniqueConstraint("scheme_key", name="uq_site_pages_scheme_key"),
    )
    op.create_index("ix_site_pages_parent_path", "site_pages", ["parent_path"])


def downgrade() -> None:
    op.drop_index("ix_site_pages_parent_path", table_name="site_pages")
    op.drop_table("site_pages")
    # Schemes the old enum did not have (SELECT and any the team added) cannot be kept.
    op.execute(
        "DELETE FROM installer_accreditations WHERE scheme NOT IN ("  # noqa: S608
        + ", ".join(f"'{key}'" for key in _OLD_KEYS)  # constants of this file only
        + ")"
    )
    op.drop_constraint(
        "fk_installer_accreditations_scheme_accreditation_schemes",
        "installer_accreditations",
        type_="foreignkey",
    )
    enum = postgresql.ENUM(*_OLD_KEYS, name="accreditation_scheme")
    enum.create(op.get_bind())
    op.alter_column(
        "installer_accreditations",
        "scheme",
        type_=enum,
        existing_nullable=False,
        postgresql_using="scheme::accreditation_scheme",
    )
    op.drop_table("accreditation_schemes")
