"""add durable background job runtime

Revision ID: 202607110005
Revises: 202607110004
Create Date: 2026-07-11 23:50:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "202607110005"
down_revision: str | None = "202607110004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("owner_user_id", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=160), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_of_job_id", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_background_jobs_owner_user_id", "background_jobs", ["owner_user_id"])
    op.create_index("ix_background_jobs_kind", "background_jobs", ["kind"])
    op.create_index("ix_background_jobs_status", "background_jobs", ["status"])
    op.create_index("ix_background_jobs_lease_owner", "background_jobs", ["lease_owner"])
    op.create_index("ix_background_jobs_lease_expires_at", "background_jobs", ["lease_expires_at"])
    op.create_index("ix_background_jobs_retry_of_job_id", "background_jobs", ["retry_of_job_id"])
    op.create_index(
        "ix_background_jobs_status_available", "background_jobs", ["status", "available_at"]
    )
    op.create_index(
        "ix_background_jobs_owner_created", "background_jobs", ["owner_user_id", "created_at"]
    )
    op.create_index(
        "ix_background_jobs_resource",
        "background_jobs",
        ["owner_user_id", "resource_type", "resource_id"],
    )

    op.create_table(
        "background_job_events",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(length=80),
            sa.ForeignKey("background_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_user_id", sa.String(length=80), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "sequence", name="uq_background_job_events_sequence"),
    )
    op.create_index("ix_background_job_events_job_id", "background_job_events", ["job_id"])
    op.create_index(
        "ix_background_job_events_owner_user_id", "background_job_events", ["owner_user_id"]
    )
    op.create_index(
        "ix_background_job_events_owner_job_sequence",
        "background_job_events",
        ["owner_user_id", "job_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_table("background_job_events")
    op.drop_table("background_jobs")
