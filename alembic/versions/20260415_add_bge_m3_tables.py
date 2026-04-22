"""add bge-m3 embedding tables

Revision ID: 20260415_add_bge_m3_tables
Revises: 20260414_tables_for_embedding
Create Date: 2026-04-15 00:00:00
"""
from __future__ import annotations

from alembic import op


revision = "20260415_add_bge_m3_tables"
down_revision = "20260414_tables_for_embedding"
branch_labels = None
depends_on = None


PROFILE_TABLE_KOR = "new_company_profile_embedding_bge_m3_kor"
PROFILE_TABLE_ENG = "new_company_profile_embedding_bge_m3_eng"
EVIDENCE_TABLE_KOR = "new_company_evidence_embedding_bge_m3_kor"
EVIDENCE_TABLE_ENG = "new_company_evidence_embedding_bge_m3_eng"


def _create_table(name: str) -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {name} (
          id uuid PRIMARY KEY,
          exhibitor_id uuid NOT NULL REFERENCES new_company(id) ON DELETE CASCADE,
          external_id text NULL,
          lang varchar(8) NOT NULL,
          content text NOT NULL,
          content_hash varchar(64) NOT NULL,
          embedding_dim integer NOT NULL,
          embedding vector NULL,
          model text NOT NULL,
          source_field text NULL,
          chunk_index integer NULL,
          chunk_typ varchar(32) NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_{name}_exhibitor_content_hash UNIQUE (exhibitor_id, content_hash)
        )
        """
    )
    op.create_index(op.f(f"ix_{name}_exhibitor_id"), name, ["exhibitor_id"], unique=False)
    op.create_index(op.f(f"ix_{name}_content_hash"), name, ["content_hash"], unique=False)
    op.create_index(op.f(f"ix_{name}_chunk_typ"), name, ["chunk_typ"], unique=False)


def _drop_table(name: str) -> None:
    op.drop_index(op.f(f"ix_{name}_chunk_typ"), table_name=name)
    op.drop_index(op.f(f"ix_{name}_content_hash"), table_name=name)
    op.drop_index(op.f(f"ix_{name}_exhibitor_id"), table_name=name)
    op.drop_table(name)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    _create_table(PROFILE_TABLE_KOR)
    _create_table(PROFILE_TABLE_ENG)
    _create_table(EVIDENCE_TABLE_KOR)
    _create_table(EVIDENCE_TABLE_ENG)


def downgrade() -> None:
    _drop_table(EVIDENCE_TABLE_ENG)
    _drop_table(EVIDENCE_TABLE_KOR)
    _drop_table(PROFILE_TABLE_ENG)
    _drop_table(PROFILE_TABLE_KOR)
