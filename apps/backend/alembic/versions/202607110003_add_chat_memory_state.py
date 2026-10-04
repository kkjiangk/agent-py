"""add chat session memory state

Revision ID: 202607110003
Revises: 202607110002
Create Date: 2026-07-11 21:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "202607110003"
down_revision: str | None = "202607110002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "memory_mode",
                sa.String(length=40),
                nullable=False,
                server_default="every_30_turns",
            )
        )
        batch_op.add_column(sa.Column("memory_summary", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("compacted_message_count", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("context_tokens", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("last_compacted_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.drop_column("last_compacted_at")
        batch_op.drop_column("context_tokens")
        batch_op.drop_column("compacted_message_count")
        batch_op.drop_column("memory_summary")
        batch_op.drop_column("memory_mode")
