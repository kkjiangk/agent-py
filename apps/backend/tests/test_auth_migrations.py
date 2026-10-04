from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from super_ai.memory.models import Base


def test_auth_tables_are_migrated_without_plaintext_secret_columns(tmp_path: Path) -> None:
    database_path = tmp_path / "auth.sqlite3"
    command.upgrade(_alembic_config(database_path), "head")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        session_columns = {column["name"] for column in inspector.get_columns("auth_sessions")}
        index_names = {
            index["name"]
            for table_name in ("users", "auth_sessions")
            for index in inspector.get_indexes(table_name)
        }
    finally:
        engine.dispose()

    assert {"users", "auth_sessions"} <= table_names
    expected_user_columns = {
        "id",
        "email",
        "display_name",
        "password_hash",
        "created_at",
        "updated_at",
    }
    expected_session_columns = {
        "id",
        "user_id",
        "token_hash",
        "created_at",
        "last_seen_at",
        "revoked_at",
    }

    assert expected_user_columns <= user_columns
    assert {"password", "plain_password"} & user_columns == set()
    assert expected_session_columns <= session_columns
    assert {"token", "access_token"} & session_columns == set()
    assert {"ix_users_email", "ix_auth_sessions_token_hash"} <= index_names


def test_auth_metadata_exposes_user_and_session_tables() -> None:
    tables = Base.metadata.tables

    assert {"users", "auth_sessions"} <= set(tables)
    assert "password_hash" in tables["users"].c
    assert "token_hash" in tables["auth_sessions"].c
    assert "password" not in tables["users"].c
    assert "token" not in tables["auth_sessions"].c


def _alembic_config(database_path: Path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    return config
