"""KPRINT QA 봇 퀵메뉴/카테고리 CSV 적재용 테이블.

Revision ID: 20260430_kprint_qa_quickmenu
Revises: 20260429_msg_meta_retrieval_topic

- CSV 컬럼과 1:1에 가깝게 보관 (primary_question=true 가 메인 화면 1차 버튼 후보).
- PostgreSQL 예약어 회피: CSV ``user`` → 컬럼 ``qa_user``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260430_kprint_qa_quickmenu"
down_revision = "20260429_msg_meta_retrieval_topic"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kprint_qa_quickmenu",
        sa.Column("qna_code", sa.Text(), primary_key=True, nullable=False),
        sa.Column("primary_question", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("parent_id", sa.Text(), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=True),
        sa.Column("quickmenu_label", sa.Text(), nullable=True),
        sa.Column("qa_user", sa.Text(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("subcategory", sa.Text(), nullable=True),
        sa.Column("question_sample", sa.Text(), nullable=True),
        sa.Column("answer_sample", sa.Text(), nullable=True),
        sa.Column("links", sa.Text(), nullable=True),
        sa.Column("utm", sa.Text(), nullable=True),
        sa.Column("follow_question1", sa.Text(), nullable=True),
        sa.Column("follow_question2", sa.Text(), nullable=True),
        sa.Column("follow_question3", sa.Text(), nullable=True),
        sa.Column("follow_question4", sa.Text(), nullable=True),
        sa.Column("follow_question5_formoreinformation", sa.Text(), nullable=True),
        sa.Column("default_quickmenu", sa.Text(), nullable=True),
        sa.Column("default_answer_type", sa.Text(), nullable=True),
        sa.Column("default_answer_prompt", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
    )
    op.create_index("ix_kprint_qa_quickmenu_parent_depth", "kprint_qa_quickmenu", ["parent_id", "depth"])
    op.create_index("ix_kprint_qa_quickmenu_primary_parent", "kprint_qa_quickmenu", ["primary_question", "parent_id"])


def downgrade() -> None:
    op.drop_index("ix_kprint_qa_quickmenu_primary_parent", table_name="kprint_qa_quickmenu")
    op.drop_index("ix_kprint_qa_quickmenu_parent_depth", table_name="kprint_qa_quickmenu")
    op.drop_table("kprint_qa_quickmenu")
