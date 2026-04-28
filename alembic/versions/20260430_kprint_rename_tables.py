"""Rename KOBA tables to KPRINT tables when needed.

Revision ID: 20260430_kprint_rename
Revises: 20260429_drop_bge_m3
"""
from __future__ import annotations

from alembic import op


revision = "20260430_kprint_rename"
down_revision = "20260429_drop_bge_m3"
branch_labels = None
depends_on = None


def _rename_table_if_exists(old: str, new: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
          IF to_regclass('{old}') IS NOT NULL AND to_regclass('{new}') IS NULL THEN
            EXECUTE 'ALTER TABLE ' || quote_ident('{old}') || ' RENAME TO ' || quote_ident('{new}');
          END IF;
        END
        $$;
        """
    )


def _rename_index_if_exists(old: str, new: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
          IF to_regclass('{old}') IS NOT NULL AND to_regclass('{new}') IS NULL THEN
            EXECUTE 'ALTER INDEX ' || quote_ident('{old}') || ' RENAME TO ' || quote_ident('{new}');
          END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    _rename_table_if_exists("koba_exhibitor", "kprint_exhibitor")
    _rename_table_if_exists("koba_exhibit_item", "kprint_exhibit_item")

    _rename_table_if_exists(
        "koba_exhibitor_profile_embedding_qwen3_0_6b_kor",
        "kprint_exhibitor_profile_embedding_qwen3_0_6b_kor",
    )
    _rename_table_if_exists(
        "koba_exhibitor_profile_embedding_qwen3_0_6b_eng",
        "kprint_exhibitor_profile_embedding_qwen3_0_6b_eng",
    )
    _rename_table_if_exists(
        "koba_exhibitor_evidence_embedding_qwen3_0_6b_kor",
        "kprint_exhibitor_evidence_embedding_qwen3_0_6b_kor",
    )
    _rename_table_if_exists(
        "koba_exhibitor_evidence_embedding_qwen3_0_6b_eng",
        "kprint_exhibitor_evidence_embedding_qwen3_0_6b_eng",
    )
    _rename_table_if_exists(
        "koba_exhibit_item_profile_embedding_qwen3_0_6b_kor",
        "kprint_exhibit_item_profile_embedding_qwen3_0_6b_kor",
    )
    _rename_table_if_exists(
        "koba_exhibit_item_profile_embedding_qwen3_0_6b_eng",
        "kprint_exhibit_item_profile_embedding_qwen3_0_6b_eng",
    )
    _rename_table_if_exists(
        "koba_exhibit_item_evidence_embedding_qwen3_0_6b_kor",
        "kprint_exhibit_item_evidence_embedding_qwen3_0_6b_kor",
    )
    _rename_table_if_exists(
        "koba_exhibit_item_evidence_embedding_qwen3_0_6b_eng",
        "kprint_exhibit_item_evidence_embedding_qwen3_0_6b_eng",
    )

    _rename_index_if_exists("ix_koba_exhibitor_booth_number", "ix_kprint_exhibitor_booth_number")
    _rename_index_if_exists("ix_koba_exhibitor_country_code", "ix_kprint_exhibitor_country_code")
    _rename_index_if_exists("ix_koba_exhibitor_exhibit_year", "ix_kprint_exhibitor_exhibit_year")
    _rename_index_if_exists("ix_koba_exhibitor_external_id", "ix_kprint_exhibitor_external_id")
    _rename_index_if_exists("ix_koba_exhibit_item_product_id", "ix_kprint_exhibit_item_product_id")
    _rename_index_if_exists("ix_koba_exhibit_item_exhibitor_sn", "ix_kprint_exhibit_item_exhibitor_sn")
    _rename_index_if_exists("ix_koba_exhibit_item_external_id", "ix_kprint_exhibit_item_external_id")


def downgrade() -> None:
    _rename_table_if_exists("kprint_exhibitor", "koba_exhibitor")
    _rename_table_if_exists("kprint_exhibit_item", "koba_exhibit_item")
