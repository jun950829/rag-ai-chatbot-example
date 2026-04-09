"""create company and product tables

Revision ID: 20260403_0001
Revises:
Create Date: 2026-04-03 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260403_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("logo_url", sa.String(length=2048), nullable=True),
        sa.Column("name_kor", sa.Text(), nullable=True),
        sa.Column("name_eng", sa.Text(), nullable=True),
        sa.Column("desc_kor", sa.Text(), nullable=True),
        sa.Column("desc_eng", sa.Text(), nullable=True),
        sa.Column("homepage", sa.String(length=512), nullable=True),
        sa.Column("tel", sa.String(length=50), nullable=True),
        sa.Column("exhibit_year", sa.Integer(), nullable=True),
        sa.Column("exhibition_category", sa.String(length=100), nullable=True),
        sa.Column("booth_number", sa.String(length=50), nullable=True),
        sa.Column("exhibit_hall_label_kor", sa.String(length=100), nullable=True),
        sa.Column("exhibit_hall_label_eng", sa.String(length=100), nullable=True),
        sa.Column("country_code", sa.String(length=16), nullable=True),
        sa.Column("country_label_kor", sa.String(length=100), nullable=True),
        sa.Column("country_label_eng", sa.String(length=100), nullable=True),
        sa.Column("address_kor", sa.Text(), nullable=True),
        sa.Column("address_eng", sa.Text(), nullable=True),
        sa.Column("item_main_categories_kor", sa.JSON(), nullable=False),
        sa.Column("item_main_categories_eng", sa.JSON(), nullable=False),
        sa.Column("item_sub_categories_kor", sa.JSON(), nullable=False),
        sa.Column("item_sub_categories_eng", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index(op.f("ix_company_booth_number"), "company", ["booth_number"], unique=False)
    op.create_index(op.f("ix_company_country_code"), "company", ["country_code"], unique=False)
    op.create_index(op.f("ix_company_exhibit_year"), "company", ["exhibit_year"], unique=False)
    op.create_index(op.f("ix_company_external_id"), "company", ["external_id"], unique=False)

    op.create_table(
        "product",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("image_url", sa.String(length=2048), nullable=True),
        sa.Column("name_kor", sa.Text(), nullable=True),
        sa.Column("name_eng", sa.Text(), nullable=True),
        sa.Column("description_kor", sa.Text(), nullable=True),
        sa.Column("description_eng", sa.Text(), nullable=True),
        sa.Column("certification_kor", sa.Text(), nullable=True),
        sa.Column("certification_eng", sa.Text(), nullable=True),
        sa.Column("keywords_kor", sa.Text(), nullable=True),
        sa.Column("keywords_eng", sa.Text(), nullable=True),
        sa.Column("main_category_code", sa.String(length=50), nullable=True),
        sa.Column("main_category_kor", sa.Text(), nullable=True),
        sa.Column("main_category_eng", sa.Text(), nullable=True),
        sa.Column("sub_category_code", sa.String(length=50), nullable=True),
        sa.Column("sub_category_kor", sa.Text(), nullable=True),
        sa.Column("sub_category_eng", sa.Text(), nullable=True),
        sa.Column("model_name", sa.Text(), nullable=True),
        sa.Column("manufacturer_kor", sa.Text(), nullable=True),
        sa.Column("manufacturer_eng", sa.Text(), nullable=True),
        sa.Column("country_of_origin_code", sa.String(length=50), nullable=True),
        sa.Column("country_of_origin_kor", sa.String(length=100), nullable=True),
        sa.Column("country_of_origin_eng", sa.String(length=100), nullable=True),
        sa.Column("exhibit_year", sa.Integer(), nullable=True),
        sa.Column("exhibition_category", sa.String(length=100), nullable=True),
        sa.Column("exhibit_hall_label_kor", sa.String(length=100), nullable=True),
        sa.Column("exhibit_hall_label_eng", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["company.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index(op.f("ix_product_company_id"), "product", ["company_id"], unique=False)
    op.create_index(op.f("ix_product_exhibit_year"), "product", ["exhibit_year"], unique=False)
    op.create_index(op.f("ix_product_external_id"), "product", ["external_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_product_external_id"), table_name="product")
    op.drop_index(op.f("ix_product_exhibit_year"), table_name="product")
    op.drop_index(op.f("ix_product_company_id"), table_name="product")
    op.drop_table("product")

    op.drop_index(op.f("ix_company_external_id"), table_name="company")
    op.drop_index(op.f("ix_company_exhibit_year"), table_name="company")
    op.drop_index(op.f("ix_company_country_code"), table_name="company")
    op.drop_index(op.f("ix_company_booth_number"), table_name="company")
    op.drop_table("company")
