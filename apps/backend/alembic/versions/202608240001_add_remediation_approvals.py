"""add remediation approval gate

Revision ID: 202608240001
Revises: 202607110007
Create Date: 2026-08-24 20:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "202608240001"
down_revision: str | None = "202607110007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "aiops_remediation_approvals",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("owner_user_id", sa.String(length=80), nullable=False),
        sa.Column(
            "task_id",
            sa.String(length=80),
            sa.ForeignKey("aiops_diagnostic_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(length=160), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decided_by_user_id", sa.String(length=80), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatch_status", sa.String(length=20), nullable=False),
        sa.Column("dispatch_error", sa.Text(), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "risk_level IN ('low', 'medium', 'high', 'critical')",
            name="ck_aiops_remediation_approvals_risk",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_aiops_remediation_approvals_status",
        ),
    )
    op.create_index(
        "ix_aiops_remediation_approvals_owner_user_id",
        "aiops_remediation_approvals",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_aiops_remediation_approvals_task_id",
        "aiops_remediation_approvals",
        ["task_id"],
    )
    op.create_index(
        "ix_aiops_remediation_approvals_owner_task_created",
        "aiops_remediation_approvals",
        ["owner_user_id", "task_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("aiops_remediation_approvals")
