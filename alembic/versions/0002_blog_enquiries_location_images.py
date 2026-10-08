"""Blog posts, direct installer enquiries, managed location images, optional quote phone.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
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
    # The phone number on the last step of the quote form is optional.
    op.alter_column("quote_requests", "phone", existing_type=sa.String(length=30), nullable=True)

    # Admin-managed location photos: alt text, photo credit and the Cloudinary asset id.
    op.add_column("locations", sa.Column("image_alt", sa.String(length=160), nullable=True))
    op.add_column("locations", sa.Column("image_credit", sa.String(length=160), nullable=True))
    op.add_column("locations", sa.Column("image_public_id", sa.String(length=255), nullable=True))

    op.create_table(
        "installer_enquiries",
        sa.Column("installer_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("ip_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "sent_to_installer", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["installer_id"],
            ["installers.id"],
            name=op.f("fk_installer_enquiries_installer_id_installers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_installer_enquiries")),
    )
    op.create_index(
        "ix_installer_enquiries_created_at", "installer_enquiries", ["created_at"], unique=False
    )
    op.create_index(
        "ix_installer_enquiries_installer_id_created_at",
        "installer_enquiries",
        ["installer_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_installer_enquiries_ip_hash"), "installer_enquiries", ["ip_hash"], unique=False
    )

    op.create_table(
        "blog_posts",
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("excerpt", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False),
        sa.Column("category_slug", sa.String(length=80), nullable=False),
        sa.Column("author_name", sa.String(length=80), nullable=False),
        sa.Column("cover_image_url", sa.String(length=500), nullable=True),
        sa.Column("cover_image_alt", sa.String(length=160), nullable=True),
        sa.Column("cover_image_public_id", sa.String(length=255), nullable=True),
        sa.Column("seo_title", sa.String(length=70), nullable=True),
        sa.Column("seo_description", sa.String(length=160), nullable=True),
        sa.Column("reading_minutes", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_featured", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("draft", "published", name="blog_post_status"),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_blog_posts")),
        sa.UniqueConstraint("slug", name=op.f("uq_blog_posts_slug")),
    )
    op.create_index(
        op.f("ix_blog_posts_category_slug"), "blog_posts", ["category_slug"], unique=False
    )
    op.create_index(
        "ix_blog_posts_status_published_at",
        "blog_posts",
        ["status", "published_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_blog_posts_status_published_at", table_name="blog_posts")
    op.drop_index(op.f("ix_blog_posts_category_slug"), table_name="blog_posts")
    op.drop_table("blog_posts")
    sa.Enum(name="blog_post_status").drop(op.get_bind(), checkfirst=True)

    op.drop_index(op.f("ix_installer_enquiries_ip_hash"), table_name="installer_enquiries")
    op.drop_index(
        "ix_installer_enquiries_installer_id_created_at", table_name="installer_enquiries"
    )
    op.drop_index("ix_installer_enquiries_created_at", table_name="installer_enquiries")
    op.drop_table("installer_enquiries")

    op.drop_column("locations", "image_public_id")
    op.drop_column("locations", "image_credit")
    op.drop_column("locations", "image_alt")

    # Requests sent without a phone number keep an empty value rather than block the downgrade.
    op.execute("UPDATE quote_requests SET phone = '' WHERE phone IS NULL")
    op.alter_column("quote_requests", "phone", existing_type=sa.String(length=30), nullable=False)
