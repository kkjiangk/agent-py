"""add standard chat skill metadata

Revision ID: 202607110004
Revises: 202607110003
Create Date: 2026-07-11 22:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "202607110004"
down_revision: str | None = "202607110003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_chat_skills") as batch_op:
        batch_op.add_column(sa.Column("name", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("description", sa.String(length=1024), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT id, content FROM user_chat_skills")
    ).mappings()
    for row in rows:
        skill_name = f"legacy-skill-{str(row['id'])[-12:].lower()}"
        description = "由旧版聊天配置迁移的 Skill；请重新上传标准 SKILL.md 以补充准确描述。"
        content = str(row["content"])
        if not content.lstrip().startswith("---"):
            content = (
                f"---\nname: {skill_name}\ndescription: {description}\n---\n\n{content}"
            )
        connection.execute(
            sa.text(
                "UPDATE user_chat_skills "
                "SET name = :name, description = :description, content = :content "
                "WHERE id = :id"
            ),
            {
                "id": row["id"],
                "name": skill_name,
                "description": description,
                "content": content,
            },
        )

    with op.batch_alter_table("user_chat_skills") as batch_op:
        batch_op.alter_column("name", existing_type=sa.String(length=64), nullable=False)
        batch_op.alter_column(
            "description", existing_type=sa.String(length=1024), nullable=False
        )
        batch_op.create_unique_constraint(
            "uq_user_chat_skills_owner_name", ["owner_user_id", "name"]
        )


def downgrade() -> None:
    with op.batch_alter_table("user_chat_skills") as batch_op:
        batch_op.drop_constraint("uq_user_chat_skills_owner_name", type_="unique")
        batch_op.drop_column("description")
        batch_op.drop_column("name")
