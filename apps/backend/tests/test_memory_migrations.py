from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import JSON, create_engine, inspect

from super_ai.memory.models import Base

REQUIRED_MEMORY_TABLES = {
    "document_index_tasks",
    "chat_sessions",
    "chat_messages",
    "aiops_diagnostic_tasks",
    "aiops_diagnostic_reports",
    "aiops_tool_call_audits",
    "aiops_graph_checkpoints",
    "tool_call_audits",
    "user_chat_configurations",
    "user_chat_prompts",
    "user_chat_skills",
}


def test_alembic_upgrade_creates_memory_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "memory.sqlite3"
    command.upgrade(_alembic_config(database_path), "head")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        table_columns = {
            table_name: {column["name"] for column in inspector.get_columns(table_name)}
            for table_name in REQUIRED_MEMORY_TABLES
        }
        index_names = {
            index["name"]
            for table_name in REQUIRED_MEMORY_TABLES
            for index in inspector.get_indexes(table_name)
        }
    finally:
        engine.dispose()

    assert REQUIRED_MEMORY_TABLES <= table_names
    assert "alembic_version" in table_names
    assert all("owner_user_id" in columns for columns in table_columns.values())
    assert {
        "ix_document_index_tasks_owner_document_created_at",
        "ix_document_index_tasks_owner_status",
        "ix_chat_sessions_owner_updated_at",
        "ix_chat_messages_owner_session_created_at",
        "ix_aiops_diagnostic_tasks_owner_created_at",
        "ix_chat_messages_session_created_at",
        "ix_aiops_diagnostic_tasks_created_at",
        "ix_aiops_tool_call_audits_task_created_at",
        "ix_aiops_graph_checkpoints_task_thread",
        "ix_tool_call_audits_owner_session_created_at",
        "ix_tool_call_audits_owner_diagnostic_created_at",
        "ix_user_chat_prompts_owner_default",
        "ix_user_chat_prompts_owner_updated_at",
        "ix_user_chat_skills_owner_filename",
        "ix_user_chat_skills_owner_updated_at",
    } <= index_names


def test_memory_metadata_exposes_required_tables_and_json_columns() -> None:
    tables = Base.metadata.tables

    assert REQUIRED_MEMORY_TABLES <= set(tables)
    assert all("owner_user_id" in tables[table_name].c for table_name in REQUIRED_MEMORY_TABLES)
    assert "failure_reason" in tables["document_index_tasks"].c
    assert "retry_of_task_id" in tables["document_index_tasks"].c
    assert isinstance(tables["chat_messages"].c["metadata"].type, JSON)
    assert isinstance(tables["aiops_diagnostic_tasks"].c["input_payload"].type, JSON)
    assert isinstance(tables["aiops_diagnostic_reports"].c["payload"].type, JSON)
    assert isinstance(tables["aiops_tool_call_audits"].c["arguments"].type, JSON)
    assert isinstance(tables["tool_call_audits"].c["arguments"].type, JSON)
    assert "chat_session_id" in tables["tool_call_audits"].c
    assert "diagnostic_task_id" in tables["tool_call_audits"].c
    assert isinstance(tables["aiops_graph_checkpoints"].c["checkpoint_payload"].type, JSON)
    assert "content" in tables["user_chat_prompts"].c
    assert "content" in tables["user_chat_skills"].c
    assert "name" in tables["user_chat_skills"].c
    assert "description" in tables["user_chat_skills"].c


def _alembic_config(database_path: Path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    return config
