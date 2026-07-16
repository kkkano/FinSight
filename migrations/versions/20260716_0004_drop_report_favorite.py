"""删除已下线的报告收藏字段。

Revision ID: 20260716_0004
Revises: 20260716_0003
Create Date: 2026-07-16
"""
from __future__ import annotations

from alembic import op


revision = "20260716_0004"
down_revision = "20260716_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE reports DROP COLUMN IF EXISTS is_favorite")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE reports ADD COLUMN IF NOT EXISTS "
        "is_favorite BOOLEAN NOT NULL DEFAULT false"
    )
