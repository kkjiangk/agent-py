"""add owner scoped user feedback

Revision ID: 202607110006
Revises: 202607110005
Create Date: 2026-07-11 23:51:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "202607110006"
down_revision: str | None = "202607110005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_feedback",
        sa.Column("id", sa.String(length=80), primary_key=True),
        sa.Column("owner_user_id", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.String(length=160), nullable=False),
        sa.Column("subject_key", sa.String(length=160), nullable=False),
        sa.Column("rating", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.String(length=80), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("correction", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "owner_user_id",
            "target_type",
            "target_id",
            "subject_key",
            name="uq_user_feedback_target",
        ),
    )
    op.create_index("ix_user_feedback_owner_user_id", "user_feedback", ["owner_user_id"])
    op.create_index(
        "ix_user_feedback_owner_target",
        "user_feedback",
        ["owner_user_id", "target_type", "target_id"],
    )


def downgrade() -> None:
    op.drop_table("user_feedback")
