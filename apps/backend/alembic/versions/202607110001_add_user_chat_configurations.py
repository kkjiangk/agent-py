"""add user chat configurations

Revision ID: 202607110001
Revises: 202607100003
Create Date: 2026-07-11 01:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "202607110001"
down_revision: str | None = "202607100003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_chat_configurations",
        sa.Column("owner_user_id", sa.String(length=80), nullable=False),
        sa.Column("system_prompt_id", sa.String(length=120), nullable=False),
        sa.Column("skill_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("owner_user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_chat_configurations")
