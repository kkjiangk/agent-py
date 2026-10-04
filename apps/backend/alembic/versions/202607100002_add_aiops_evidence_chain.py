"""add AIOps evidence-chain persistence

Revision ID: 202607100002
Revises: 202607100001
Create Date: 2026-07-10 00:02:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "202607100002"
down_revision: str | None = "202607100001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "aiops_diagnostic_steps",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("owner_user_id", sa.String(length=80), nullable=False),
        sa.Column("task_id", sa.String(length=80), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["aiops_diagnostic_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_aiops_diagnostic_steps_owner_user_id",
        "aiops_diagnostic_steps",
        ["owner_user_id"],
    )
    op.create_index("ix_aiops_diagnostic_steps_task_id", "aiops_diagnostic_steps", ["task_id"])
    op.create_index(
        "ix_aiops_diagnostic_steps_owner_task_sequence",
        "aiops_diagnostic_steps",
        ["owner_user_id", "task_id", "sequence"],
    )

    op.create_table(
        "aiops_diagnostic_evidence",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("owner_user_id", sa.String(length=80), nullable=False),
        sa.Column("task_id", sa.String(length=80), nullable=False),
        sa.Column("step_id", sa.String(length=80), nullable=True),
        sa.Column("tool_call_id", sa.String(length=160), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=240), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["step_id"], ["aiops_diagnostic_steps.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["aiops_diagnostic_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_aiops_diagnostic_evidence_owner_user_id",
        "aiops_diagnostic_evidence",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_aiops_diagnostic_evidence_task_id",
        "aiops_diagnostic_evidence",
        ["task_id"],
    )
    op.create_index(
        "ix_aiops_diagnostic_evidence_step_id",
        "aiops_diagnostic_evidence",
        ["step_id"],
    )
    op.create_index(
        "ix_aiops_diagnostic_evidence_tool_call_id",
        "aiops_diagnostic_evidence",
        ["tool_call_id"],
    )
    op.create_index(
        "ix_aiops_diagnostic_evidence_owner_task_created_at",
        "aiops_diagnostic_evidence",
        ["owner_user_id", "task_id", "created_at"],
    )
    op.create_index(
        "ix_aiops_diagnostic_evidence_owner_task_kind",
        "aiops_diagnostic_evidence",
        ["owner_user_id", "task_id", "kind"],
    )

    op.create_table(
        "aiops_report_evidence_links",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("owner_user_id", sa.String(length=80), nullable=False),
        sa.Column("task_id", sa.String(length=80), nullable=False),
        sa.Column("report_id", sa.String(length=80), nullable=False),
        sa.Column("evidence_id", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["evidence_id"], ["aiops_diagnostic_evidence.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["report_id"], ["aiops_diagnostic_reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["aiops_diagnostic_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_aiops_report_evidence_links_owner_user_id",
        "aiops_report_evidence_links",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_aiops_report_evidence_links_task_id",
        "aiops_report_evidence_links",
        ["task_id"],
    )
    op.create_index(
        "ix_aiops_report_evidence_links_report_id",
        "aiops_report_evidence_links",
        ["report_id"],
    )
    op.create_index(
        "ix_aiops_report_evidence_links_evidence_id",
        "aiops_report_evidence_links",
        ["evidence_id"],
    )
    op.create_index(
        "ix_aiops_report_evidence_links_owner_report",
        "aiops_report_evidence_links",
        ["owner_user_id", "report_id"],
    )
    op.create_index(
        "ix_aiops_report_evidence_links_owner_task_evidence",
        "aiops_report_evidence_links",
        ["owner_user_id", "task_id", "evidence_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_aiops_report_evidence_links_owner_task_evidence",
        table_name="aiops_report_evidence_links",
    )
    op.drop_index(
        "ix_aiops_report_evidence_links_owner_report", table_name="aiops_report_evidence_links"
    )
    op.drop_index(
        "ix_aiops_report_evidence_links_evidence_id", table_name="aiops_report_evidence_links"
    )
    op.drop_index(
        "ix_aiops_report_evidence_links_report_id", table_name="aiops_report_evidence_links"
    )
    op.drop_index(
        "ix_aiops_report_evidence_links_task_id", table_name="aiops_report_evidence_links"
    )
    op.drop_index(
        "ix_aiops_report_evidence_links_owner_user_id", table_name="aiops_report_evidence_links"
    )
    op.drop_table("aiops_report_evidence_links")

    op.drop_index(
        "ix_aiops_diagnostic_evidence_owner_task_kind", table_name="aiops_diagnostic_evidence"
    )
    op.drop_index(
        "ix_aiops_diagnostic_evidence_owner_task_created_at",
        table_name="aiops_diagnostic_evidence",
    )
    op.drop_index(
        "ix_aiops_diagnostic_evidence_tool_call_id", table_name="aiops_diagnostic_evidence"
    )
    op.drop_index("ix_aiops_diagnostic_evidence_step_id", table_name="aiops_diagnostic_evidence")
    op.drop_index("ix_aiops_diagnostic_evidence_task_id", table_name="aiops_diagnostic_evidence")
    op.drop_index(
        "ix_aiops_diagnostic_evidence_owner_user_id", table_name="aiops_diagnostic_evidence"
    )
    op.drop_table("aiops_diagnostic_evidence")

    op.drop_index(
        "ix_aiops_diagnostic_steps_owner_task_sequence",
        table_name="aiops_diagnostic_steps",
    )
    op.drop_index("ix_aiops_diagnostic_steps_task_id", table_name="aiops_diagnostic_steps")
    op.drop_index("ix_aiops_diagnostic_steps_owner_user_id", table_name="aiops_diagnostic_steps")
    op.drop_table("aiops_diagnostic_steps")
