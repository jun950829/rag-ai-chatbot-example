"""create new_company table

Revision ID: 20260410_create_new_company
Revises: 20260403_0001
Create Date: 2026-04-09 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260410_create_new_company"
down_revision = "20260403_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # drop table ( company and product 가 있다면, 없으면 무시)
    op.execute("DROP TABLE IF EXISTS product")
    op.execute("DROP TABLE IF EXISTS company")
    
    op.create_table(
        "new_company",
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
    op.create_index(op.f("ix_new_company_booth_number"), "new_company", ["booth_number"], unique=False)
    op.create_index(op.f("ix_new_company_country_code"), "new_company", ["country_code"], unique=False)
    op.create_index(op.f("ix_new_company_exhibit_year"), "new_company", ["exhibit_year"], unique=False)
    op.create_index(op.f("ix_new_company_external_id"), "new_company", ["external_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_new_company_external_id"), table_name="new_company")
    op.drop_index(op.f("ix_new_company_exhibit_year"), table_name="new_company")
    op.drop_index(op.f("ix_new_company_country_code"), table_name="new_company")
    op.drop_index(op.f("ix_new_company_booth_number"), table_name="new_company")
    op.drop_table("new_company")