"""add tenant scope to memory records

Revision ID: 202607080003
Revises: 202607080002
Create Date: 2026-07-08 00:03:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "202607080003"
down_revision: str | None = "202607080002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCOPED_TABLES = (
    "chat_sessions",
    "chat_messages",
    "aiops_diagnostic_tasks",
    "aiops_diagnostic_reports",
    "aiops_tool_call_audits",
    "aiops_graph_checkpoints",
)


def upgrade() -> None:
    for table_name in SCOPED_TABLES:
        op.add_column(
            table_name,
            sa.Column(
                "owner_user_id",
                sa.String(length=80),
                nullable=False,
                server_default="legacy_owner",
            ),
        )

    op.create_index(
        "ix_chat_sessions_owner_updated_at",
        "chat_sessions",
        ["owner_user_id", "updated_at"],
    )
    op.create_index(
        "ix_chat_messages_owner_session_created_at",
        "chat_messages",
        ["owner_user_id", "session_id", "created_at"],
    )
    op.create_index(
        "ix_aiops_diagnostic_tasks_owner_created_at",
        "aiops_diagnostic_tasks",
        ["owner_user_id", "created_at"],
    )
    op.create_index(
        "ix_aiops_diagnostic_reports_owner_task_created_at",
        "aiops_diagnostic_reports",
        ["owner_user_id", "task_id", "created_at"],
    )
    op.create_index(
        "ix_aiops_tool_call_audits_owner_task_created_at",
        "aiops_tool_call_audits",
        ["owner_user_id", "task_id", "created_at"],
    )
    op.create_index(
        "ix_aiops_graph_checkpoints_owner_task_thread",
        "aiops_graph_checkpoints",
        ["owner_user_id", "task_id", "thread_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_aiops_graph_checkpoints_owner_task_thread",
        table_name="aiops_graph_checkpoints",
    )
    op.drop_index(
        "ix_aiops_tool_call_audits_owner_task_created_at",
        table_name="aiops_tool_call_audits",
    )
    op.drop_index(
        "ix_aiops_diagnostic_reports_owner_task_created_at",
        table_name="aiops_diagnostic_reports",
    )
    op.drop_index(
        "ix_aiops_diagnostic_tasks_owner_created_at",
        table_name="aiops_diagnostic_tasks",
    )
    op.drop_index(
        "ix_chat_messages_owner_session_created_at",
        table_name="chat_messages",
    )
    op.drop_index("ix_chat_sessions_owner_updated_at", table_name="chat_sessions")

    for table_name in reversed(SCOPED_TABLES):
        op.drop_column(table_name, "owner_user_id")
