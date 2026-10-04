"""add knowledge document metadata

Revision ID: 202607090001
Revises: 202607080003
Create Date: 2026-07-09 00:01:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "202607090001"
down_revision: str | None = "202607080003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("owner_user_id", sa.String(length=80), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=80), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("mime_type", sa.String(length=160), nullable=False),
        sa.Column("content_hash", sa.String(length=96), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("index_status", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=1024), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_documents_content_hash",
        "knowledge_documents",
        ["content_hash"],
    )
    op.create_index(
        "ix_knowledge_documents_knowledge_base_id",
        "knowledge_documents",
        ["knowledge_base_id"],
    )
    op.create_index(
        "ix_knowledge_documents_owner_user_id",
        "knowledge_documents",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_knowledge_documents_owner_kb_document",
        "knowledge_documents",
        ["owner_user_id", "knowledge_base_id", "id"],
    )
    op.create_index(
        "ix_knowledge_documents_owner_kb_hash",
        "knowledge_documents",
        ["owner_user_id", "knowledge_base_id", "content_hash"],
    )
    op.create_index(
        "ix_knowledge_documents_owner_kb_uploaded_at",
        "knowledge_documents",
        ["owner_user_id", "knowledge_base_id", "uploaded_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_documents_owner_kb_uploaded_at",
        table_name="knowledge_documents",
    )
    op.drop_index("ix_knowledge_documents_owner_kb_hash", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_owner_kb_document", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_owner_user_id", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_knowledge_base_id", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_content_hash", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
