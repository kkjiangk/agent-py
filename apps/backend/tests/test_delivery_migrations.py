from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_upgrade_backfills_only_unsent_approved_commands_and_downgrade_preserves_approvals(
    tmp_path: Path,
) -> None:
    path = tmp_path / "migration.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path}")
    command.upgrade(config, "202608240001")
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text("""
                INSERT INTO aiops_diagnostic_tasks
                (id, owner_user_id, status, query, input_payload, result_payload,
                created_at, updated_at)
                VALUES ('diag', 'owner', 'succeeded', 'test', '{}', '{}', CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP)
            """)
            )
            for identifier, status, dispatch in [
                ("recover", "approved", "failed"),
                ("sent", "approved", "dispatched"),
                ("pending", "pending", "pending"),
                ("rejected", "rejected", "not_applicable"),
            ]:
                connection.execute(
                    text("""
                    INSERT INTO aiops_remediation_approvals
                    (id, owner_user_id, task_id, tool_name, arguments, rationale, risk_level,
                    status, dispatch_status, created_at, updated_at)
                    VALUES (:id, 'owner', 'diag', 'RestartService', '{}', 'reviewed', 'high',
                    :status, :dispatch, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """),
                    {"id": identifier, "status": status, "dispatch": dispatch},
                )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            jobs = connection.execute(
                text("SELECT resource_id, status, kind FROM background_jobs")
            ).all()
        assert jobs == [("recover", "queued", "remediation_dispatch")]
        command.downgrade(config, "202608240001")
        columns = {
            column["name"] for column in inspect(engine).get_columns("aiops_remediation_approvals")
        }
        assert "dispatch_lease_owner" not in columns
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM aiops_remediation_approvals")) == 4
            assert connection.scalar(text("SELECT COUNT(*) FROM background_jobs")) == 0
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM background_jobs")) == 1
    finally:
        engine.dispose()
