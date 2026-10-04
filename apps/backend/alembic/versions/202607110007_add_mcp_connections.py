"""add managed MCP connections

Revision ID: 202607110007
Revises: 202607110006
Create Date: 2026-07-11 23:52:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "202607110007"
down_revision: str | None = "202607110006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_connections",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("owner_user_id", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("transport", sa.String(length=40), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("retries", sa.Integer(), nullable=False),
        sa.Column("last_check_ok", sa.Boolean(), nullable=True),
        sa.Column("last_tool_count", sa.Integer(), nullable=True),
        sa.Column("last_tools", sa.JSON(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_user_id", "name", name="uq_mcp_connections_owner_name"),
    )
    op.create_index("ix_mcp_connections_owner_user_id", "mcp_connections", ["owner_user_id"])
    op.create_index(
        "ix_mcp_connections_owner_updated",
        "mcp_connections",
        ["owner_user_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_table("mcp_connections")
