"""Add conversation sessions + messages persistence.

Revision ID: 20260428_chat_persist
Revises: 20260430_kprint_item_text
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260428_chat_persist"
down_revision = "20260430_kprint_item_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector 확장 (임베딩 테이블/향후 message embedding에 활용)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "conversation_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversation_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_index("ix_messages_session_id", "messages", ["session_id"])
    op.create_index("ix_messages_session_id_created_at_desc", "messages", ["session_id", sa.text("created_at DESC")])

    op.create_table(
        "message_meta",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("intent", sa.Text(), nullable=False),
        sa.Column("is_followup", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_index("ix_message_meta_message_id", "message_meta", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_message_meta_message_id", table_name="message_meta")
    op.drop_table("message_meta")

    op.drop_index("ix_messages_session_id_created_at_desc", table_name="messages")
    op.drop_index("ix_messages_session_id", table_name="messages")
    op.drop_table("messages")

    op.drop_table("conversation_sessions")

