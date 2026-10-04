"""add user chat prompt and skill assets

Revision ID: 202607110002
Revises: 202607110001
Create Date: 2026-07-11 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "202607110002"
down_revision: str | None = "202607110001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_chat_prompts",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("owner_user_id", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_chat_prompts_owner_default",
        "user_chat_prompts",
        ["owner_user_id", "is_default"],
        unique=False,
    )
    op.create_index(
        "ix_user_chat_prompts_owner_updated_at",
        "user_chat_prompts",
        ["owner_user_id", "updated_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_chat_prompts_owner_user_id"),
        "user_chat_prompts",
        ["owner_user_id"],
        unique=False,
    )

    op.create_table(
        "user_chat_skills",
        sa.Column("id", sa.String(length=80), nullable=False),
        sa.Column("owner_user_id", sa.String(length=80), nullable=False),
        sa.Column("filename", sa.String(length=240), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_chat_skills_owner_filename",
        "user_chat_skills",
        ["owner_user_id", "filename"],
        unique=False,
    )
    op.create_index(
        "ix_user_chat_skills_owner_updated_at",
        "user_chat_skills",
        ["owner_user_id", "updated_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_chat_skills_owner_user_id"),
        "user_chat_skills",
        ["owner_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_chat_skills_owner_user_id"), table_name="user_chat_skills")
    op.drop_index("ix_user_chat_skills_owner_updated_at", table_name="user_chat_skills")
    op.drop_index("ix_user_chat_skills_owner_filename", table_name="user_chat_skills")
    op.drop_table("user_chat_skills")
    op.drop_index(op.f("ix_user_chat_prompts_owner_user_id"), table_name="user_chat_prompts")
    op.drop_index("ix_user_chat_prompts_owner_updated_at", table_name="user_chat_prompts")
    op.drop_index("ix_user_chat_prompts_owner_default", table_name="user_chat_prompts")
    op.drop_table("user_chat_prompts")
