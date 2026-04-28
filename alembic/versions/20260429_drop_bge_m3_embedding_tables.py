"""Remove legacy BGE-M3 embedding tables (no longer used).

Revision ID: 20260429_drop_bge_m3_embedding_tables
Revises: 20260428_koba_replace_new_company
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260429_drop_bge_m3_embedding_tables"
down_revision = "20260428_koba_replace_new_company"
branch_labels = None
depends_on = None

_BGE_TABLES = (
    "koba_exhibit_item_evidence_embedding_bge_m3_eng",
    "koba_exhibit_item_evidence_embedding_bge_m3_kor",
    "koba_exhibit_item_profile_embedding_bge_m3_eng",
    "koba_exhibit_item_profile_embedding_bge_m3_kor",
    "koba_exhibitor_evidence_embedding_bge_m3_eng",
    "koba_exhibitor_evidence_embedding_bge_m3_kor",
    "koba_exhibitor_profile_embedding_bge_m3_eng",
    "koba_exhibitor_profile_embedding_bge_m3_kor",
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
