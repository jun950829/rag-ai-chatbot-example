"""set embedding tables for new_company

Revision ID: 20260414_tables_for_embedding
Revises: 20260410_create_new_company
Create Date: 2026-04-14 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260414_tables_for_embedding"
down_revision = "20260410_create_new_company"
branch_labels = None
depends_on = None


PROFILE_TABLE_KOR = "new_company_profile_embedding_qwen3_0_6b_kor"
PROFILE_TABLE_ENG = "new_company_profile_embedding_qwen3_0_6b_eng"
EVIDENCE_TABLE_KOR = "new_company_evidence_embedding_qwen3_0_6b_kor"
EVIDENCE_TABLE_ENG = "new_company_evidence_embedding_qwen3_0_6b_eng"


def _create_table(name: str) -> None:
    op.execute(
        f"""
        CREATE TABLE {name} (
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
    op.execute(f"DROP TABLE IF EXISTS {PROFILE_TABLE_KOR}")
    op.execute(f"DROP TABLE IF EXISTS {PROFILE_TABLE_ENG}")
    op.execute(f"DROP TABLE IF EXISTS {EVIDENCE_TABLE_KOR}")
    op.execute(f"DROP TABLE IF EXISTS {EVIDENCE_TABLE_ENG}")

    _create_table(PROFILE_TABLE_KOR)
    _create_table(PROFILE_TABLE_ENG)
    _create_table(EVIDENCE_TABLE_KOR)
    _create_table(EVIDENCE_TABLE_ENG)


def downgrade() -> None:
    _drop_table(EVIDENCE_TABLE_ENG)
    _drop_table(EVIDENCE_TABLE_KOR)
    _drop_table(PROFILE_TABLE_ENG)
    _drop_table(PROFILE_TABLE_KOR)

