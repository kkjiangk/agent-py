"""add structured diagnosis cases

Revision ID: 202607100003
Revises: 202607100002
Create Date: 2026-07-10 00:03:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "202607100003"
down_revision: str | None = "202607100002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "aiops_diagnostic_cases",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("owner_user_id", sa.String(length=80), nullable=False),
        sa.Column("task_id", sa.String(length=80), nullable=False),
        sa.Column("report_id", sa.String(length=80), nullable=False),
        sa.Column("document_id", sa.String(length=80), nullable=False),
        sa.Column("index_task_id", sa.String(length=80), nullable=False),
        sa.Column("alert_name", sa.String(length=240), nullable=False),
        sa.Column("service", sa.String(length=240), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=False),
        sa.Column("remediation", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["index_task_id"], ["document_index_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["aiops_diagnostic_reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["aiops_diagnostic_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
        sa.UniqueConstraint("document_id"),
        sa.UniqueConstraint("index_task_id"),
    )
    op.create_index(
        "ix_aiops_diagnostic_cases_owner_user_id",
        "aiops_diagnostic_cases",
        ["owner_user_id"],
    )
    op.create_index("ix_aiops_diagnostic_cases_task_id", "aiops_diagnostic_cases", ["task_id"])
    op.create_index("ix_aiops_diagnostic_cases_report_id", "aiops_diagnostic_cases", ["report_id"])
    op.create_index(
        "ix_aiops_diagnostic_cases_document_id",
        "aiops_diagnostic_cases",
        ["document_id"],
    )
    op.create_index(
        "ix_aiops_diagnostic_cases_index_task_id",
        "aiops_diagnostic_cases",
        ["index_task_id"],
    )
    op.create_index(
        "ix_aiops_diagnostic_cases_owner_created_at",
        "aiops_diagnostic_cases",
        ["owner_user_id", "created_at"],
    )
    op.create_index(
        "ix_aiops_diagnostic_cases_owner_service",
        "aiops_diagnostic_cases",
        ["owner_user_id", "service"],
    )


def downgrade() -> None:
    op.drop_index("ix_aiops_diagnostic_cases_owner_service", table_name="aiops_diagnostic_cases")
    op.drop_index("ix_aiops_diagnostic_cases_owner_created_at", table_name="aiops_diagnostic_cases")
    op.drop_index("ix_aiops_diagnostic_cases_index_task_id", table_name="aiops_diagnostic_cases")
    op.drop_index("ix_aiops_diagnostic_cases_document_id", table_name="aiops_diagnostic_cases")
    op.drop_index("ix_aiops_diagnostic_cases_report_id", table_name="aiops_diagnostic_cases")
    op.drop_index("ix_aiops_diagnostic_cases_task_id", table_name="aiops_diagnostic_cases")
    op.drop_index("ix_aiops_diagnostic_cases_owner_user_id", table_name="aiops_diagnostic_cases")
    op.drop_table("aiops_diagnostic_cases")
