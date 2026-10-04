"""add generic Agent tool call audits

Revision ID: 202607100001
Revises: 202607090002
Create Date: 2026-07-10 00:01:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "202607100001"
down_revision: str | None = "202607090002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_call_audits",
        sa.Column("id", sa.String(length=160), nullable=False),
        sa.Column("owner_user_id", sa.String(length=80), nullable=False),
        sa.Column("chat_session_id", sa.String(length=80), nullable=True),
        sa.Column("diagnostic_task_id", sa.String(length=80), nullable=True),
        sa.Column("tool_name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(chat_session_id IS NOT NULL AND diagnostic_task_id IS NULL) OR "
            "(chat_session_id IS NULL AND diagnostic_task_id IS NOT NULL)",
            name="ck_tool_call_audits_one_parent",
        ),
        sa.ForeignKeyConstraint(["chat_session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["diagnostic_task_id"], ["aiops_diagnostic_tasks.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_call_audits_owner_user_id", "tool_call_audits", ["owner_user_id"])
    op.create_index("ix_tool_call_audits_chat_session_id", "tool_call_audits", ["chat_session_id"])
    op.create_index(
        "ix_tool_call_audits_diagnostic_task_id",
        "tool_call_audits",
        ["diagnostic_task_id"],
    )
    op.create_index(
        "ix_tool_call_audits_owner_session_created_at",
        "tool_call_audits",
        ["owner_user_id", "chat_session_id", "created_at"],
    )
    op.create_index(
        "ix_tool_call_audits_owner_diagnostic_created_at",
        "tool_call_audits",
        ["owner_user_id", "diagnostic_task_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_tool_call_audits_owner_diagnostic_created_at", table_name="tool_call_audits")
    op.drop_index("ix_tool_call_audits_owner_session_created_at", table_name="tool_call_audits")
    op.drop_index("ix_tool_call_audits_diagnostic_task_id", table_name="tool_call_audits")
    op.drop_index("ix_tool_call_audits_chat_session_id", table_name="tool_call_audits")
    op.drop_index("ix_tool_call_audits_owner_user_id", table_name="tool_call_audits")
    op.drop_table("tool_call_audits")
