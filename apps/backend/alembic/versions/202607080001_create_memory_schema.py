"""create memory schema

Revision ID: 202607080001
Revises:
Create Date: 2026-07-08 00:01:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "202607080001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "aiops_diagnostic_tasks",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_aiops_diagnostic_tasks_created_at",
        "aiops_diagnostic_tasks",
        ["created_at"],
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("session_id", sa.String(length=80), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_messages_session_id", "chat_messages", ["session_id"])
    op.create_index(
        "ix_chat_messages_session_created_at",
        "chat_messages",
        ["session_id", "created_at"],
    )
    op.create_table(
        "aiops_diagnostic_reports",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("task_id", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["aiops_diagnostic_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_aiops_diagnostic_reports_task_id", "aiops_diagnostic_reports", ["task_id"])
    op.create_index(
        "ix_aiops_diagnostic_reports_task_created_at",
        "aiops_diagnostic_reports",
        ["task_id", "created_at"],
    )
    op.create_table(
        "aiops_tool_call_audits",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("task_id", sa.String(length=80), nullable=False),
        sa.Column("tool_name", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["aiops_diagnostic_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_aiops_tool_call_audits_task_id", "aiops_tool_call_audits", ["task_id"])
    op.create_index(
        "ix_aiops_tool_call_audits_task_created_at",
        "aiops_tool_call_audits",
        ["task_id", "created_at"],
    )
    op.create_table(
        "aiops_graph_checkpoints",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("task_id", sa.String(length=80), nullable=False),
        sa.Column("thread_id", sa.String(length=160), nullable=False),
        sa.Column("checkpoint_ns", sa.String(length=160), nullable=False),
        sa.Column("checkpoint_id", sa.String(length=160), nullable=False),
        sa.Column("checkpoint_payload", sa.JSON(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["aiops_diagnostic_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_aiops_graph_checkpoints_task_id", "aiops_graph_checkpoints", ["task_id"])
    op.create_index(
        "ix_aiops_graph_checkpoints_task_thread",
        "aiops_graph_checkpoints",
        ["task_id", "thread_id"],
    )
    op.create_index(
        "ix_aiops_graph_checkpoints_identity",
        "aiops_graph_checkpoints",
        ["thread_id", "checkpoint_ns", "checkpoint_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_aiops_graph_checkpoints_identity", table_name="aiops_graph_checkpoints")
    op.drop_index("ix_aiops_graph_checkpoints_task_thread", table_name="aiops_graph_checkpoints")
    op.drop_index("ix_aiops_graph_checkpoints_task_id", table_name="aiops_graph_checkpoints")
    op.drop_table("aiops_graph_checkpoints")
    op.drop_index("ix_aiops_tool_call_audits_task_created_at", table_name="aiops_tool_call_audits")
    op.drop_index("ix_aiops_tool_call_audits_task_id", table_name="aiops_tool_call_audits")
    op.drop_table("aiops_tool_call_audits")
    op.drop_index(
        "ix_aiops_diagnostic_reports_task_created_at",
        table_name="aiops_diagnostic_reports",
    )
    op.drop_index("ix_aiops_diagnostic_reports_task_id", table_name="aiops_diagnostic_reports")
    op.drop_table("aiops_diagnostic_reports")
    op.drop_index("ix_chat_messages_session_created_at", table_name="chat_messages")
    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_aiops_diagnostic_tasks_created_at", table_name="aiops_diagnostic_tasks")
    op.drop_table("aiops_diagnostic_tasks")
    op.drop_table("chat_sessions")
