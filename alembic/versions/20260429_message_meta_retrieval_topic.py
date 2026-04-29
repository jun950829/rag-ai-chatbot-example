"""message_meta에 검색 주제(retrieval_topic) 컬럼 추가.

Revision ID: 20260429_msg_meta_retrieval_topic
Revises: 20260428_chat_persist

목적:
- 대화 의도(intent: followup 등)와 벡터 검색 축(회사/제품/전체)을 DB에 분리 저장한다.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260429_msg_meta_retrieval_topic"
down_revision = "20260428_chat_persist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 단계 1: 기존 행은 전체 검색(all)으로 간주 ---
    op.add_column(
        "message_meta",
        sa.Column(
            "retrieval_topic",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'all'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("message_meta", "retrieval_topic")
