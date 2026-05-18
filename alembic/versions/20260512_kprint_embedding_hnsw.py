"""Optional HNSW indexes on KPRINT Qwen3 embedding tables (cosine).

Revision ID: 20260512_kprint_hnsw
Revises: 20260430_kprint_qa_quickmenu

Large tables: index creation may take time. Uses partial index WHERE embedding IS NOT NULL.
"""

from __future__ import annotations

from alembic import op

revision = "20260512_kprint_hnsw"
down_revision = "20260430_kprint_qa_quickmenu"
branch_labels = None
depends_on = None

_KPRINT_EMBEDDING_TABLES = (
    "kprint_exhibitor_profile_embedding_qwen3_0_6b_kor",
    "kprint_exhibitor_profile_embedding_qwen3_0_6b_eng",
    "kprint_exhibitor_evidence_embedding_qwen3_0_6b_kor",
    "kprint_exhibitor_evidence_embedding_qwen3_0_6b_eng",
    "kprint_exhibit_item_profile_embedding_qwen3_0_6b_kor",
    "kprint_exhibit_item_profile_embedding_qwen3_0_6b_eng",
    "kprint_exhibit_item_evidence_embedding_qwen3_0_6b_kor",
    "kprint_exhibit_item_evidence_embedding_qwen3_0_6b_eng",
)


def upgrade() -> None:
    for tbl in _KPRINT_EMBEDDING_TABLES:
        idx = f"ix_{tbl}_embedding_hnsw_cosine"
        op.execute(
            f"""
            CREATE INDEX IF NOT EXISTS {idx}
            ON {tbl}
            USING hnsw (embedding vector_cosine_ops)
            WHERE embedding IS NOT NULL
            """
        )


def downgrade() -> None:
    for tbl in _KPRINT_EMBEDDING_TABLES:
        idx = f"ix_{tbl}_embedding_hnsw_cosine"
        op.execute(f"DROP INDEX IF EXISTS {idx}")
