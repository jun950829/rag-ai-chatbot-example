"""Remove legacy BGE-M3 embedding tables (no longer used).

Revision ID: 20260429_drop_bge_m3
Revises: 20260428_kprint_init
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260429_drop_bge_m3"
down_revision = "20260428_kprint_init"
branch_labels = None
depends_on = None

_BGE_TABLES = (
    "kprint_exhibit_item_evidence_embedding_bge_m3_eng",
    "kprint_exhibit_item_evidence_embedding_bge_m3_kor",
    "kprint_exhibit_item_profile_embedding_bge_m3_eng",
    "kprint_exhibit_item_profile_embedding_bge_m3_kor",
    "kprint_exhibitor_evidence_embedding_bge_m3_eng",
    "kprint_exhibitor_evidence_embedding_bge_m3_kor",
    "kprint_exhibitor_profile_embedding_bge_m3_eng",
    "kprint_exhibitor_profile_embedding_bge_m3_kor",
    "new_company_evidence_embedding_bge_m3_eng",
    "new_company_evidence_embedding_bge_m3_kor",
    "new_company_profile_embedding_bge_m3_eng",
    "new_company_profile_embedding_bge_m3_kor",
)


def upgrade() -> None:
    for name in _BGE_TABLES:
        op.execute(sa.text(f'DROP TABLE IF EXISTS "{name}" CASCADE'))


def downgrade() -> None:
    op.execute("SELECT 1")
