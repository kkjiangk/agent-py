"""Add fenced dispatch leases and recover previously approved commands.

Revision ID: 202610040001
Revises: 202608240001
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from hashlib import sha256

import sqlalchemy as sa
from alembic import op

revision = "202610040001"
down_revision: str | None = "202608240001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "aiops_remediation_approvals",
        sa.Column("dispatch_lease_owner", sa.String(80), nullable=True),
    )
    op.add_column(
        "aiops_remediation_approvals",
        sa.Column("dispatch_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    connection = op.get_bind()
    approvals = sa.table(
        "aiops_remediation_approvals",
        sa.column("id", sa.String()),
        sa.column("owner_user_id", sa.String()),
        sa.column("status", sa.String()),
        sa.column("dispatch_status", sa.String()),
    )
    jobs = sa.table(
        "background_jobs",
        *(
            sa.column(name, type_)
            for name, type_ in (
                ("id", sa.String()),
                ("owner_user_id", sa.String()),
                ("kind", sa.String()),
                ("resource_type", sa.String()),
                ("resource_id", sa.String()),
                ("status", sa.String()),
                ("payload", sa.JSON()),
                ("attempt", sa.Integer()),
                ("max_attempts", sa.Integer()),
                ("timeout_seconds", sa.Integer()),
                ("available_at", sa.DateTime()),
                ("created_at", sa.DateTime()),
                ("updated_at", sa.DateTime()),
            )
        ),
    )
    now = datetime.now(timezone.utc)
    pending = connection.execute(
        sa.select(approvals.c.id, approvals.c.owner_user_id).where(
            approvals.c.status == "approved", approvals.c.dispatch_status != "dispatched"
        )
    ).mappings()
    for approval in pending:
        approval_id = str(approval["id"])
        connection.execute(
            jobs.insert().values(
                id=f"dispatch_{sha256(approval_id.encode()).hexdigest()[:32]}",
                owner_user_id=approval["owner_user_id"],
                kind="remediation_dispatch",
                resource_type="remediation_approval",
                resource_id=approval_id,
                status="queued",
                payload={"approvalId": approval_id},
                attempt=0,
                max_attempts=10,
                timeout_seconds=30,
                available_at=now,
                created_at=now,
                updated_at=now,
            )
        )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM background_jobs WHERE kind='remediation_dispatch'"))
    op.drop_column("aiops_remediation_approvals", "dispatch_lease_expires_at")
    op.drop_column("aiops_remediation_approvals", "dispatch_lease_owner")
