"""Drop new_company + legacy embedding tables; add KPRINT exhibitor/item + embeddings.

Revision ID: 20260428_kprint_init
Revises: 20260415_add_bge_m3_tables
"""
from __future__ import annotations

import hashlib

from alembic import op
import sqlalchemy as sa


revision = "20260428_kprint_init"
down_revision = "20260415_add_bge_m3_tables"
branch_labels = None
depends_on = None


_LEGACY_EMBEDDING_TABLES = (
    "new_company_evidence_embedding_bge_m3_eng",
    "new_company_evidence_embedding_bge_m3_kor",
    "new_company_profile_embedding_bge_m3_eng",
    "new_company_profile_embedding_bge_m3_kor",
    "new_company_evidence_embedding_qwen3_0_6b_eng",
    "new_company_evidence_embedding_qwen3_0_6b_kor",
    "new_company_profile_embedding_qwen3_0_6b_eng",
    "new_company_profile_embedding_qwen3_0_6b_kor",
)


def _drop_legacy() -> None:
    for name in _LEGACY_EMBEDDING_TABLES:
        op.execute(sa.text(f'DROP TABLE IF EXISTS "{name}" CASCADE'))
    op.execute(sa.text('DROP TABLE IF EXISTS "new_company" CASCADE'))


def _emb_ix(name: str, kind: str) -> str:
    """Short deterministic index names (PG identifier limit)."""
    h = hashlib.sha256(f"{name}:{kind}".encode()).hexdigest()[:10]
    return f"emb_{h}_{kind}"


def _create_embedding_table(name: str, parent_table: str) -> None:
    op.execute(
        sa.text(
            f"""
            CREATE TABLE "{name}" (
              id uuid PRIMARY KEY,
              entity_id uuid NOT NULL REFERENCES {parent_table}(id) ON DELETE CASCADE,
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
              UNIQUE (entity_id, content_hash)
            )
            """
        )
    )
    op.execute(sa.text(f'CREATE INDEX "{_emb_ix(name, "eid")}" ON "{name}" (entity_id)'))
    op.execute(sa.text(f'CREATE INDEX "{_emb_ix(name, "ch")}" ON "{name}" (content_hash)'))
    op.execute(sa.text(f'CREATE INDEX "{_emb_ix(name, "ct")}" ON "{name}" (chunk_typ)'))


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    _drop_legacy()

    op.create_table(
        "kprint_exhibitor",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("company_name_kor", sa.Text(), nullable=True),
        sa.Column("company_name_eng", sa.Text(), nullable=True),
        sa.Column("homepage", sa.String(length=512), nullable=True),
        sa.Column("exhibit_year", sa.Integer(), nullable=True),
        sa.Column("exhibition_category_label", sa.String(length=100), nullable=True),
        sa.Column("booth_number", sa.String(length=50), nullable=True),
        sa.Column("country_code", sa.String(length=16), nullable=True),
        sa.Column("country_label_kor", sa.String(length=100), nullable=True),
        sa.Column("country_label_eng", sa.String(length=100), nullable=True),
        sa.Column("exhibit_hall_code", sa.String(length=50), nullable=True),
        sa.Column("exhibit_hall_label_kor", sa.String(length=100), nullable=True),
        sa.Column("exhibit_hall_label_eng", sa.String(length=100), nullable=True),
        sa.Column("exhibit_status_code", sa.String(length=50), nullable=True),
        sa.Column("exhibit_status_label_kor", sa.String(length=100), nullable=True),
        sa.Column("exhibit_status_label_eng", sa.String(length=100), nullable=True),
        sa.Column("badge_list", sa.JSON(), nullable=False),
        sa.Column("badge_label_kor_list", sa.JSON(), nullable=False),
        sa.Column("badge_label_eng_list", sa.JSON(), nullable=False),
        sa.Column("item_main_category_label_kor_list", sa.JSON(), nullable=False),
        sa.Column("item_main_category_label_eng_list", sa.JSON(), nullable=False),
        sa.Column("item_sub_category_label_kor_list", sa.JSON(), nullable=False),
        sa.Column("item_sub_category_label_eng_list", sa.JSON(), nullable=False),
        sa.Column("company_address_kor", sa.Text(), nullable=True),
        sa.Column("company_address_eng", sa.Text(), nullable=True),
        sa.Column("exhibition_manager_tel", sa.String(length=50), nullable=True),
        sa.Column("company_description_kor", sa.Text(), nullable=True),
        sa.Column("company_description_eng", sa.Text(), nullable=True),
        sa.Column("drawing_info_company_name_kor", sa.Text(), nullable=True),
        sa.Column("drawing_info_company_name_eng", sa.Text(), nullable=True),
        sa.Column("drawing_info_company_x_coordinate_kor", sa.Integer(), nullable=True),
        sa.Column("drawing_info_company_x_coordinate_eng", sa.Integer(), nullable=True),
        sa.Column("drawing_info_company_y_coordinate_kor", sa.Integer(), nullable=True),
        sa.Column("drawing_info_company_y_coordinate_eng", sa.Integer(), nullable=True),
        sa.Column("company_logo_link", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index(op.f("ix_kprint_exhibitor_booth_number"), "kprint_exhibitor", ["booth_number"], unique=False)
    op.create_index(op.f("ix_kprint_exhibitor_country_code"), "kprint_exhibitor", ["country_code"], unique=False)
    op.create_index(op.f("ix_kprint_exhibitor_exhibit_year"), "kprint_exhibitor", ["exhibit_year"], unique=False)
    op.create_index(op.f("ix_kprint_exhibitor_external_id"), "kprint_exhibitor", ["external_id"], unique=False)

    op.create_table(
        "kprint_exhibit_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=512), nullable=True),
        sa.Column("product_id", sa.String(length=64), nullable=True),
        sa.Column("exhibitor_sn", sa.String(length=255), nullable=True),
        sa.Column("item_main_category", sa.String(length=64), nullable=True),
        sa.Column("item_main_category_label_kor", sa.String(length=255), nullable=True),
        sa.Column("item_main_category_label_eng", sa.String(length=255), nullable=True),
        sa.Column("item_sub_category", sa.String(length=64), nullable=True),
        sa.Column("item_sub_category_label_kor", sa.String(length=255), nullable=True),
        sa.Column("item_sub_category_label_eng", sa.String(length=255), nullable=True),
        sa.Column("product_name_kor", sa.Text(), nullable=True),
        sa.Column("product_name_eng", sa.Text(), nullable=True),
        sa.Column("search_keywords_kor", sa.Text(), nullable=True),
        sa.Column("search_keywords_eng", sa.Text(), nullable=True),
        sa.Column("country_of_origin", sa.String(length=32), nullable=True),
        sa.Column("country_of_origin_label_kor", sa.String(length=128), nullable=True),
        sa.Column("country_of_origin_label_eng", sa.String(length=128), nullable=True),
        sa.Column("model_name", sa.String(length=512), nullable=True),
        sa.Column("manufacturer_kor", sa.Text(), nullable=True),
        sa.Column("manufacturer_eng", sa.Text(), nullable=True),
        sa.Column("product_description_kor", sa.Text(), nullable=True),
        sa.Column("product_description_eng", sa.Text(), nullable=True),
        sa.Column("certification_status_kor", sa.String(length=255), nullable=True),
        sa.Column("certification_status_eng", sa.String(length=255), nullable=True),
        sa.Column("company_name_kor", sa.Text(), nullable=True),
        sa.Column("company_name_eng", sa.Text(), nullable=True),
        sa.Column("exhibit_year", sa.Integer(), nullable=True),
        sa.Column("exhibition_category_label", sa.String(length=100), nullable=True),
        sa.Column("exhibit_hall", sa.String(length=64), nullable=True),
        sa.Column("exhibit_hall_label_kor", sa.String(length=255), nullable=True),
        sa.Column("exhibit_hall_label_eng", sa.String(length=255), nullable=True),
        sa.Column("exhibit_status", sa.String(length=64), nullable=True),
        sa.Column("exhibit_status_label_kor", sa.String(length=255), nullable=True),
        sa.Column("exhibit_status_label_eng", sa.String(length=255), nullable=True),
        sa.Column("product_image_link", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index(op.f("ix_kprint_exhibit_item_product_id"), "kprint_exhibit_item", ["product_id"], unique=False)
    op.create_index(op.f("ix_kprint_exhibit_item_exhibitor_sn"), "kprint_exhibit_item", ["exhibitor_sn"], unique=False)
    op.create_index(op.f("ix_kprint_exhibit_item_external_id"), "kprint_exhibit_item", ["external_id"], unique=False)

    exhibitor_tables = (
        "kprint_exhibitor_profile_embedding_qwen3_0_6b_kor",
        "kprint_exhibitor_profile_embedding_qwen3_0_6b_eng",
        "kprint_exhibitor_evidence_embedding_qwen3_0_6b_kor",
        "kprint_exhibitor_evidence_embedding_qwen3_0_6b_eng",
    )
    item_tables = (
        "kprint_exhibit_item_profile_embedding_qwen3_0_6b_kor",
        "kprint_exhibit_item_profile_embedding_qwen3_0_6b_eng",
        "kprint_exhibit_item_evidence_embedding_qwen3_0_6b_kor",
        "kprint_exhibit_item_evidence_embedding_qwen3_0_6b_eng",
    )
    for t in exhibitor_tables:
        _create_embedding_table(t, "kprint_exhibitor")
    for t in item_tables:
        _create_embedding_table(t, "kprint_exhibit_item")


def downgrade() -> None:
    item_tables = (
        "kprint_exhibit_item_evidence_embedding_qwen3_0_6b_eng",
        "kprint_exhibit_item_evidence_embedding_qwen3_0_6b_kor",
        "kprint_exhibit_item_profile_embedding_qwen3_0_6b_eng",
        "kprint_exhibit_item_profile_embedding_qwen3_0_6b_kor",
    )
    exhibitor_tables = (
        "kprint_exhibitor_evidence_embedding_qwen3_0_6b_eng",
        "kprint_exhibitor_evidence_embedding_qwen3_0_6b_kor",
        "kprint_exhibitor_profile_embedding_qwen3_0_6b_eng",
        "kprint_exhibitor_profile_embedding_qwen3_0_6b_kor",
    )
    for name in item_tables:
        op.execute(sa.text(f'DROP INDEX IF EXISTS "{_emb_ix(name, "ct")}"'))
        op.execute(sa.text(f'DROP INDEX IF EXISTS "{_emb_ix(name, "ch")}"'))
        op.execute(sa.text(f'DROP INDEX IF EXISTS "{_emb_ix(name, "eid")}"'))
        op.drop_table(name)
    for name in exhibitor_tables:
        op.execute(sa.text(f'DROP INDEX IF EXISTS "{_emb_ix(name, "ct")}"'))
        op.execute(sa.text(f'DROP INDEX IF EXISTS "{_emb_ix(name, "ch")}"'))
        op.execute(sa.text(f'DROP INDEX IF EXISTS "{_emb_ix(name, "eid")}"'))
        op.drop_table(name)

    op.drop_index(op.f("ix_kprint_exhibit_item_external_id"), table_name="kprint_exhibit_item")
    op.drop_index(op.f("ix_kprint_exhibit_item_exhibitor_sn"), table_name="kprint_exhibit_item")
    op.drop_index(op.f("ix_kprint_exhibit_item_product_id"), table_name="kprint_exhibit_item")
    op.drop_table("kprint_exhibit_item")

    op.drop_index(op.f("ix_kprint_exhibitor_external_id"), table_name="kprint_exhibitor")
    op.drop_index(op.f("ix_kprint_exhibitor_exhibit_year"), table_name="kprint_exhibitor")
    op.drop_index(op.f("ix_kprint_exhibitor_country_code"), table_name="kprint_exhibitor")
    op.drop_index(op.f("ix_kprint_exhibitor_booth_number"), table_name="kprint_exhibitor")
    op.drop_table("kprint_exhibitor")

    # Restore previous revision state: re-run 20260410/20260414/20260415 manually if needed.
