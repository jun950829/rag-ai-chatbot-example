"""BGE-M3 embedding path removed (no-op migration; revision id kept for chain).

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


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
