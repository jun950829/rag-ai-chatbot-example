"""Widen KPRINT exhibit item label columns to TEXT.

Revision ID: 20260430_kprint_item_text
Revises: 20260430_kprint_rename
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260430_kprint_item_text"
down_revision = "20260430_kprint_rename"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Some KPRINT item columns can exceed 255 characters.
    op.alter_column("kprint_exhibit_item", "exhibitor_sn", type_=sa.Text(), existing_type=sa.String(length=255))
    op.alter_column("kprint_exhibit_item", "item_main_category_label_kor", type_=sa.Text(), existing_type=sa.String(length=255))
    op.alter_column("kprint_exhibit_item", "item_main_category_label_eng", type_=sa.Text(), existing_type=sa.String(length=255))
    op.alter_column("kprint_exhibit_item", "item_sub_category_label_kor", type_=sa.Text(), existing_type=sa.String(length=255))
    op.alter_column("kprint_exhibit_item", "item_sub_category_label_eng", type_=sa.Text(), existing_type=sa.String(length=255))
    op.alter_column("kprint_exhibit_item", "certification_status_kor", type_=sa.Text(), existing_type=sa.String(length=255))
    op.alter_column("kprint_exhibit_item", "certification_status_eng", type_=sa.Text(), existing_type=sa.String(length=255))
    op.alter_column("kprint_exhibit_item", "exhibit_hall_label_kor", type_=sa.Text(), existing_type=sa.String(length=255))
    op.alter_column("kprint_exhibit_item", "exhibit_hall_label_eng", type_=sa.Text(), existing_type=sa.String(length=255))
    op.alter_column("kprint_exhibit_item", "exhibit_status_label_kor", type_=sa.Text(), existing_type=sa.String(length=255))
    op.alter_column("kprint_exhibit_item", "exhibit_status_label_eng", type_=sa.Text(), existing_type=sa.String(length=255))


def downgrade() -> None:
    op.alter_column("kprint_exhibit_item", "exhibit_status_label_eng", type_=sa.String(length=255), existing_type=sa.Text())
    op.alter_column("kprint_exhibit_item", "exhibit_status_label_kor", type_=sa.String(length=255), existing_type=sa.Text())
    op.alter_column("kprint_exhibit_item", "exhibit_hall_label_eng", type_=sa.String(length=255), existing_type=sa.Text())
    op.alter_column("kprint_exhibit_item", "exhibit_hall_label_kor", type_=sa.String(length=255), existing_type=sa.Text())
    op.alter_column("kprint_exhibit_item", "certification_status_eng", type_=sa.String(length=255), existing_type=sa.Text())
    op.alter_column("kprint_exhibit_item", "certification_status_kor", type_=sa.String(length=255), existing_type=sa.Text())
    op.alter_column("kprint_exhibit_item", "item_sub_category_label_eng", type_=sa.String(length=255), existing_type=sa.Text())
    op.alter_column("kprint_exhibit_item", "item_sub_category_label_kor", type_=sa.String(length=255), existing_type=sa.Text())
    op.alter_column("kprint_exhibit_item", "item_main_category_label_eng", type_=sa.String(length=255), existing_type=sa.Text())
    op.alter_column("kprint_exhibit_item", "item_main_category_label_kor", type_=sa.String(length=255), existing_type=sa.Text())
    op.alter_column("kprint_exhibit_item", "exhibitor_sn", type_=sa.String(length=255), existing_type=sa.Text())

