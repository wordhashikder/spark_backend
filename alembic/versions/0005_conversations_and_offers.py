"""In-app conversations between installers and homeowners: messages and priced quotes.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("installer_id", sa.Uuid(), nullable=False),
        sa.Column("quote_match_id", sa.Uuid(), nullable=True),
        sa.Column("enquiry_id", sa.Uuid(), nullable=True),
        sa.Column("homeowner_name", sa.String(length=80), nullable=False),
        sa.Column("homeowner_email", sa.String(length=254), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("installer_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("homeowner_read_at", sa.DateTime(timezone=True), nullable=True),
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
            "(quote_match_id IS NULL) <> (enquiry_id IS NULL)",
            name=op.f("ck_conversations_exactly_one_job"),
        ),
        sa.ForeignKeyConstraint(
            ["enquiry_id"],
            ["installer_enquiries.id"],
            name=op.f("fk_conversations_enquiry_id_installer_enquiries"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["installer_id"],
            ["installers.id"],
            name=op.f("fk_conversations_installer_id_installers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["quote_match_id"],
            ["quote_matches.id"],
            name=op.f("fk_conversations_quote_match_id_quote_matches"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint("enquiry_id", name=op.f("uq_conversations_enquiry_id")),
        sa.UniqueConstraint("quote_match_id", name=op.f("uq_conversations_quote_match_id")),
    )
    op.create_index(
        op.f("ix_conversations_homeowner_email"), "conversations", ["homeowner_email"], unique=False
    )
    op.create_index(
        "ix_conversations_installer_id_last_message_at",
        "conversations",
        ["installer_id", "last_message_at"],
        unique=False,
    )
    op.create_table(
        "conversation_messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column(
            "sender",
            sa.Enum("installer", "homeowner", "team", "system", name="message_sender"),
            nullable=False,
        ),
        sa.Column("author_user_id", sa.Uuid(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
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
            ["author_user_id"],
            ["users.id"],
            name=op.f("fk_conversation_messages_author_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_conversation_messages_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_messages")),
    )
    op.create_index(
        "ix_conversation_messages_conversation_id_created_at",
        "conversation_messages",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "offers",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("installer_id", sa.Uuid(), nullable=False),
        sa.Column("reference", sa.String(length=12), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("includes_vat", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("sent", "accepted", "declined", "withdrawn", name="offer_status"),
            server_default="sent",
            nullable=False,
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response_note", sa.Text(), nullable=True),
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
        sa.CheckConstraint("amount > 0", name=op.f("ck_offers_amount_positive")),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_offers_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["installer_id"],
            ["installers.id"],
            name=op.f("fk_offers_installer_id_installers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_offers")),
        sa.UniqueConstraint("reference", name=op.f("uq_offers_reference")),
    )
    op.create_index(op.f("ix_offers_conversation_id"), "offers", ["conversation_id"], unique=False)
    op.create_index(
        "ix_offers_installer_id_created_at", "offers", ["installer_id", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_offers_installer_id_created_at", table_name="offers")
    op.drop_index(op.f("ix_offers_conversation_id"), table_name="offers")
    op.drop_table("offers")
    op.drop_index(
        "ix_conversation_messages_conversation_id_created_at",
        table_name="conversation_messages",
    )
    op.drop_table("conversation_messages")
    op.drop_index("ix_conversations_installer_id_last_message_at", table_name="conversations")
    op.drop_index(op.f("ix_conversations_homeowner_email"), table_name="conversations")
    op.drop_table("conversations")
    sa.Enum(name="offer_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="message_sender").drop(op.get_bind(), checkfirst=True)
