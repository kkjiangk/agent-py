from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.repositories import TenantScopeError
from super_ai.memory.sqlite import (
    SQLiteChatMemoryRepository,
    SQLiteDiagnosticMemoryRepository,
    SQLiteToolCallAuditRepository,
)


@pytest.mark.asyncio
async def test_tool_call_audit_repository_finalizes_chat_and_diagnostic_calls(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        session_factory = create_memory_session_factory(engine)
        chat = SQLiteChatMemoryRepository(session_factory)
        diagnostics = SQLiteDiagnosticMemoryRepository(session_factory)
        audits = SQLiteToolCallAuditRepository(session_factory)
        started_at = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        await chat.create_session(
            owner_user_id="user-a",
            session_id="chat-a",
            created_at=started_at,
        )
        diagnostic = await diagnostics.create_task(
            owner_user_id="user-a",
            task_id="diagnostic-a",
            status="running",
            query="latency",
        )

        await audits.create_for_chat_session(
            owner_user_id="user-a",
            audit_id="tool-chat-1",
            chat_session_id="chat-a",
            tool_name="knowledge_retrieval",
            arguments={"query": "restart api"},
            started_at=started_at,
        )
        completed = await audits.finalize(
            owner_user_id="user-a",
            audit_id="tool-chat-1",
            status="completed",
            result_summary="1 knowledge result",
            completed_at=started_at + timedelta(milliseconds=450),
        )
        diagnostic_audit = await audits.create_for_diagnostic_task(
            owner_user_id="user-a",
            audit_id="tool-diagnostic-1",
            diagnostic_task_id=diagnostic.id,
            tool_name="cls_query",
            arguments={"topic": "api"},
            started_at=started_at,
        )
        chat_audits = await audits.list_for_chat_session(
            owner_user_id="user-a",
            chat_session_id="chat-a",
        )
        diagnostic_audits = await audits.list_for_diagnostic_task(
            owner_user_id="user-a",
            diagnostic_task_id=diagnostic.id,
        )
    finally:
        await engine.dispose()

    assert completed is not None
    assert completed.status == "completed"
    assert completed.result_summary == "1 knowledge result"
    assert completed.duration_ms == 450
    assert completed.chat_session_id == "chat-a"
    assert completed.diagnostic_task_id is None
    assert chat_audits == [completed]
    assert diagnostic_audits == [diagnostic_audit]
    assert diagnostic_audit.diagnostic_task_id == diagnostic.id


@pytest.mark.asyncio
async def test_tool_call_audit_repository_denies_cross_tenant_parent_writes(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        session_factory = create_memory_session_factory(engine)
        chat = SQLiteChatMemoryRepository(session_factory)
        audits = SQLiteToolCallAuditRepository(session_factory)
        await chat.create_session(owner_user_id="user-a", session_id="chat-a")

        with pytest.raises(TenantScopeError):
            await audits.create_for_chat_session(
                owner_user_id="user-b",
                audit_id="tool-cross-tenant",
                chat_session_id="chat-a",
                tool_name="knowledge_retrieval",
            )
    finally:
        await engine.dispose()


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "tool-call-audits.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"
