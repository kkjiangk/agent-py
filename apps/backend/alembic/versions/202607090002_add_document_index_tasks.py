"""add document index task attempts

Revision ID: 202607090002
Revises: 202607090001
Create Date: 2026-07-09 00:02:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "202607090002"
down_revision: str | None = "202607090001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_index_tasks",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("owner_user_id", sa.String(length=80), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=80), nullable=False),
        sa.Column("document_id", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("retry_of_task_id", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_document_index_tasks_document_id",
        "document_index_tasks",
        ["document_id"],
    )
    op.create_index(
        "ix_document_index_tasks_knowledge_base_id",
        "document_index_tasks",
        ["knowledge_base_id"],
    )
    op.create_index(
        "ix_document_index_tasks_owner_user_id",
        "document_index_tasks",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_document_index_tasks_owner_document_created_at",
        "document_index_tasks",
        ["owner_user_id", "knowledge_base_id", "document_id", "created_at"],
    )
    op.create_index(
        "ix_document_index_tasks_owner_status",
        "document_index_tasks",
        ["owner_user_id", "status"],
    )
    op.create_index(
        "ix_document_index_tasks_retry_of",
        "document_index_tasks",
        ["retry_of_task_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_index_tasks_retry_of", table_name="document_index_tasks")
    op.drop_index("ix_document_index_tasks_owner_status", table_name="document_index_tasks")
    op.drop_index(
        "ix_document_index_tasks_owner_document_created_at",
        table_name="document_index_tasks",
    )
    op.drop_index("ix_document_index_tasks_owner_user_id", table_name="document_index_tasks")
    op.drop_index("ix_document_index_tasks_knowledge_base_id", table_name="document_index_tasks")
    op.drop_index("ix_document_index_tasks_document_id", table_name="document_index_tasks")
    op.drop_table("document_index_tasks")
