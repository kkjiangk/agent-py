from __future__ import annotations

import inspect
from dataclasses import is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

import super_ai.memory.repositories as repositories_module
from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.repositories import (
    ChatMemoryRepository,
    ChatMessageRecord,
    ChatSessionRecord,
    DiagnosticReportRecord,
    DiagnosticTaskRecord,
    DocumentIndexTaskRecord,
    GraphCheckpointRecord,
    KnowledgeDocumentRecord,
    TimeRangeFilter,
    ToolCallAuditRecord,
)
from super_ai.memory.sqlite import (
    SQLiteChatMemoryRepository,
    SQLiteDiagnosticMemoryRepository,
    SQLiteKnowledgeDocumentRepository,
    SQLiteUserChatPromptRepository,
    SQLiteUserChatSkillRepository,
    create_sqlite_memory_repositories,
)


@pytest.mark.asyncio
async def test_chat_repository_persists_and_queries_history(migrated_database_url: str) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        session_factory = create_memory_session_factory(engine)
        chat_repository = SQLiteChatMemoryRepository(session_factory)
        created_at = datetime(2026, 7, 8, 10, 0, tzinfo=timezone.utc)

        session = await chat_repository.create_session(
            owner_user_id="user-a",
            session_id="session-1",
            title="Production incident",
            created_at=created_at,
        )
        await chat_repository.append_message(
            owner_user_id="user-a",
            message_id="message-1",
            session_id=session.id,
            role="user",
            content="What happened?",
            metadata={"tokens": 3},
            created_at=created_at - timedelta(minutes=5),
        )
        expected_message = await chat_repository.append_message(
            owner_user_id="user-a",
            message_id="message-2",
            session_id=session.id,
            role="assistant",
            content="Investigating.",
            metadata={"sources": ["runbook"]},
            created_at=created_at + timedelta(minutes=1),
        )
        await chat_repository.append_message(
            owner_user_id="user-a",
            message_id="message-3",
            session_id=session.id,
            role="assistant",
            content="Resolved.",
            metadata={"sources": ["timeline"]},
            created_at=created_at + timedelta(minutes=30),
        )
        await chat_repository.create_session(
            owner_user_id="user-b",
            session_id="session-2",
            title="Another user's session",
            created_at=created_at,
        )
        await chat_repository.append_message(
            owner_user_id="user-b",
            message_id="message-4",
            session_id="session-2",
            role="user",
            content="Private to user B",
            created_at=created_at,
        )

        all_messages = await chat_repository.list_messages(
            owner_user_id="user-a",
            session_id=session.id,
        )
        ranged_messages = await chat_repository.list_messages(
            owner_user_id="user-a",
            session_id=session.id,
            time_range=TimeRangeFilter(
                start_at=created_at,
                end_at=created_at + timedelta(minutes=5),
            ),
        )
    finally:
        await engine.dispose()

    assert session.owner_user_id == "user-a"
    assert session.title == "Production incident"
    assert [message.id for message in all_messages] == ["message-1", "message-2", "message-3"]
    assert ranged_messages == [expected_message]
    assert all(message.owner_user_id == "user-a" for message in all_messages)
    assert ranged_messages[0].metadata == {"sources": ["runbook"]}


@pytest.mark.asyncio
async def test_chat_repository_denies_cross_tenant_parent_writes(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        session_factory = create_memory_session_factory(engine)
        chat_repository = SQLiteChatMemoryRepository(session_factory)
        await chat_repository.create_session(
            owner_user_id="user-a",
            session_id="session-a",
            title="User A",
        )

        with pytest.raises(PermissionError):
            await chat_repository.append_message(
                owner_user_id="user-b",
                message_id="message-b",
                session_id="session-a",
                role="user",
                content="cross tenant write",
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_chat_repository_updates_clears_and_deletes_sessions_by_owner(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        session_factory = create_memory_session_factory(engine)
        chat_repository = SQLiteChatMemoryRepository(session_factory)
        created_at = datetime(2026, 7, 9, 9, 0, tzinfo=timezone.utc)
        session = await chat_repository.create_session(
            owner_user_id="user-a",
            session_id="session-a",
            title=None,
            created_at=created_at,
        )
        await chat_repository.create_session(
            owner_user_id="user-b",
            session_id="session-b",
            title="Other user",
            created_at=created_at + timedelta(minutes=1),
        )
        await chat_repository.append_message(
            owner_user_id="user-a",
            message_id="message-a-1",
            session_id=session.id,
            role="user",
            content="How do I restart the API service?",
            metadata={
                "citations": [
                    {
                        "chunkId": "chunk_1",
                        "documentId": "doc_1",
                        "knowledgeBaseId": "kb_user_a",
                    }
                ],
                "toolCallIds": ["tool_call_1"],
            },
            created_at=created_at + timedelta(minutes=2),
        )
        await chat_repository.append_message(
            owner_user_id="user-a",
            message_id="message-a-2",
            session_id=session.id,
            role="assistant",
            content="Use the runbook.",
            created_at=created_at + timedelta(minutes=3),
        )

        updated = await chat_repository.update_session_title(
            owner_user_id="user-a",
            session_id=session.id,
            title="Restart API",
            updated_at=created_at + timedelta(minutes=4),
        )
        cross_tenant_update = await chat_repository.update_session_title(
            owner_user_id="user-b",
            session_id=session.id,
            title="Should not change",
            updated_at=created_at + timedelta(minutes=5),
        )
        messages_before_clear = await chat_repository.list_messages(
            owner_user_id="user-a",
            session_id=session.id,
        )
        deleted_messages = await chat_repository.clear_messages(
            owner_user_id="user-a",
            session_id=session.id,
            updated_at=created_at + timedelta(minutes=6),
        )
        messages_after_clear = await chat_repository.list_messages(
            owner_user_id="user-a",
            session_id=session.id,
        )
        cross_tenant_deleted = await chat_repository.delete_session(
            owner_user_id="user-b",
            session_id=session.id,
        )
        deleted = await chat_repository.delete_session(
            owner_user_id="user-a",
            session_id=session.id,
        )
        session_after_delete = await chat_repository.get_session(
            owner_user_id="user-a",
            session_id=session.id,
        )
    finally:
        await engine.dispose()

    assert updated is not None
    assert updated.title == "Restart API"
    assert cross_tenant_update is None
    assert messages_before_clear[0].metadata["toolCallIds"] == ["tool_call_1"]
    assert deleted_messages == 2
    assert messages_after_clear == []
    assert cross_tenant_deleted is False
    assert deleted is True
    assert session_after_delete is None


@pytest.mark.asyncio
async def test_diagnostic_repository_persists_artifacts_and_filters_tasks(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        session_factory = create_memory_session_factory(engine)
        diagnostic_repository = SQLiteDiagnosticMemoryRepository(session_factory)
        created_at = datetime(2026, 7, 8, 11, 0, tzinfo=timezone.utc)

        await diagnostic_repository.create_task(
            owner_user_id="user-a",
            task_id="task-old",
            status="completed",
            query="old incident",
            input_payload={"service": "api"},
            result_payload={"summary": "old"},
            created_at=created_at - timedelta(days=1),
        )
        await diagnostic_repository.create_task(
            owner_user_id="user-b",
            task_id="task-other-user",
            status="running",
            query="other incident",
            created_at=created_at,
        )
        task = await diagnostic_repository.create_task(
            owner_user_id="user-a",
            task_id="task-1",
            status="running",
            query="latency spike",
            input_payload={"service": "checkout"},
            result_payload={"stage": "collecting"},
            created_at=created_at,
        )
        report = await diagnostic_repository.add_report(
            owner_user_id="user-a",
            report_id="report-1",
            task_id=task.id,
            title="Latency report",
            content="p95 increased",
            payload={"p95_ms": 1200},
            created_at=created_at + timedelta(minutes=2),
        )
        audit = await diagnostic_repository.add_tool_call_audit(
            owner_user_id="user-a",
            audit_id="audit-1",
            task_id=task.id,
            tool_name="kubectl",
            status="success",
            arguments={"namespace": "prod"},
            result_payload={"pods": 3},
            error_message=None,
            started_at=created_at + timedelta(minutes=1),
            completed_at=created_at + timedelta(minutes=2),
        )
        checkpoint = await diagnostic_repository.save_checkpoint(
            owner_user_id="user-a",
            checkpoint_record_id="checkpoint-row-1",
            task_id=task.id,
            thread_id="thread-1",
            checkpoint_ns="diagnosis",
            checkpoint_id="checkpoint-1",
            checkpoint_payload={"node": "summarize"},
            metadata={"graph": "aiops"},
            created_at=created_at + timedelta(minutes=3),
        )

        ranged_tasks = await diagnostic_repository.list_tasks(
            owner_user_id="user-a",
            time_range=TimeRangeFilter(
                start_at=created_at - timedelta(minutes=1),
                end_at=created_at + timedelta(minutes=1),
            ),
        )
        reports = await diagnostic_repository.list_reports(owner_user_id="user-a", task_id=task.id)
        audits = await diagnostic_repository.list_tool_call_audits(
            owner_user_id="user-a",
            task_id=task.id,
        )
        checkpoints = await diagnostic_repository.list_checkpoints(
            owner_user_id="user-a",
            task_id=task.id,
        )
    finally:
        await engine.dispose()

    assert ranged_tasks == [task]
    assert reports == [report]
    assert audits == [audit]
    assert checkpoints == [checkpoint]
    assert task.owner_user_id == "user-a"
    assert report.owner_user_id == "user-a"
    assert audit.arguments == {"namespace": "prod"}
    assert checkpoint.checkpoint_payload == {"node": "summarize"}


@pytest.mark.asyncio
async def test_diagnostic_repository_denies_cross_tenant_artifact_writes(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        session_factory = create_memory_session_factory(engine)
        diagnostic_repository = SQLiteDiagnosticMemoryRepository(session_factory)
        await diagnostic_repository.create_task(
            owner_user_id="user-a",
            task_id="task-a",
            status="running",
            query="latency",
        )

        with pytest.raises(PermissionError):
            await diagnostic_repository.add_report(
                owner_user_id="user-b",
                report_id="report-b",
                task_id="task-a",
                title="Cross tenant",
                content="nope",
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_diagnosis_case_repository_is_owner_scoped_and_idempotent(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        created_at = datetime(2026, 7, 10, 14, 0, tzinfo=timezone.utc)
        task = await repositories.diagnostics.create_task(
            owner_user_id="user-a",
            task_id="diagnostic-case-a",
            status="succeeded",
            query="Investigate checkout timeout",
        )
        report = await repositories.diagnostics.add_report(
            owner_user_id="user-a",
            report_id="report-case-a",
            task_id=task.id,
            title="Checkout report",
            content="Evidence-backed conclusion.",
        )
        document = await repositories.documents.create_document(
            owner_user_id="user-a",
            document_id="document-case-a",
            knowledge_base_id="kb_user-a",
            filename="checkout-case.md",
            size_bytes=24,
            mime_type="text/markdown",
            content_hash="sha256:diagnosis-case-a",
            metadata={"knowledgeType": "diagnostic-case"},
            uploaded_at=created_at,
        )
        index_task = await repositories.document_index_tasks.create_task(
            owner_user_id="user-a",
            task_id="index-case-a",
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
            created_at=created_at,
        )
        case = await repositories.diagnostics.create_case(
            owner_user_id="user-a",
            case_id="case-a",
            task_id=task.id,
            report_id=report.id,
            document_id=document.id,
            index_task_id=index_task.id,
            alert_name="CheckoutTimeout",
            service="checkout",
            keywords=["checkout", "timeout"],
            root_cause="database connection pool exhausted",
            remediation="increase the pool and retry failed requests",
            summary="Evidence-backed conclusion.",
            evidence_ids=["evidence-a"],
        )
        duplicate = await repositories.diagnostics.create_case(
            owner_user_id="user-a",
            case_id="case-a-second-attempt",
            task_id=task.id,
            report_id=report.id,
            document_id=document.id,
            index_task_id=index_task.id,
            alert_name="Different alert must not replace the original",
            service="other",
            keywords=[],
            root_cause="",
            remediation="",
            summary="",
            evidence_ids=[],
        )
        owner_case = await repositories.diagnostics.get_case(
            owner_user_id="user-a",
            case_id=case.id,
        )
        other_case = await repositories.diagnostics.get_case(
            owner_user_id="user-b",
            case_id=case.id,
        )
        owner_cases = await repositories.diagnostics.list_cases(owner_user_id="user-a")
    finally:
        await engine.dispose()

    assert duplicate == case
    assert owner_case == case
    assert other_case is None
    assert owner_cases == [case]


@pytest.mark.asyncio
async def test_document_repository_persists_queries_duplicates_and_marks_deleted(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        session_factory = create_memory_session_factory(engine)
        document_repository = SQLiteKnowledgeDocumentRepository(session_factory)
        uploaded_at = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)

        document = await document_repository.create_document(
            owner_user_id="user-a",
            document_id="doc-1",
            knowledge_base_id="kb-user-a",
            filename="runbook.md",
            size_bytes=42,
            mime_type="text/markdown",
            content_hash="sha256:abc",
            status="ready",
            index_status="pending",
            metadata={"source": "upload"},
            uploaded_at=uploaded_at,
        )
        await document_repository.create_document(
            owner_user_id="user-b",
            document_id="doc-2",
            knowledge_base_id="kb-user-b",
            filename="private.md",
            size_bytes=13,
            mime_type="text/markdown",
            content_hash="sha256:abc",
        )

        duplicate = await document_repository.find_active_by_hash(
            owner_user_id="user-a",
            knowledge_base_id="kb-user-a",
            content_hash="sha256:abc",
        )
        ranged_documents = await document_repository.list_documents(
            owner_user_id="user-a",
            knowledge_base_id="kb-user-a",
            time_range=TimeRangeFilter(
                start_at=uploaded_at - timedelta(minutes=1),
                end_at=uploaded_at + timedelta(minutes=1),
            ),
        )
        deleted = await document_repository.mark_document_deleted(
            owner_user_id="user-a",
            knowledge_base_id="kb-user-a",
            document_id=document.id,
        )
        after_delete = await document_repository.list_documents(
            owner_user_id="user-a",
            knowledge_base_id="kb-user-a",
        )
    finally:
        await engine.dispose()

    assert document.owner_user_id == "user-a"
    assert document.filename == "runbook.md"
    assert document.metadata == {"source": "upload"}
    assert duplicate == document
    assert ranged_documents == [document]
    assert deleted is not None
    assert deleted.status == "deleted"
    assert after_delete == []


@pytest.mark.asyncio
async def test_document_index_task_repository_tracks_status_failure_and_retry(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        session_factory = create_memory_session_factory(engine)
        repositories = create_sqlite_memory_repositories(session_factory)
        created_at = datetime(2026, 7, 9, 14, 0, tzinfo=timezone.utc)

        await repositories.documents.create_document(
            owner_user_id="user-a",
            document_id="doc-1",
            knowledge_base_id="kb-user-a",
            filename="runbook.md",
            size_bytes=42,
            mime_type="text/markdown",
            content_hash="sha256:index",
            metadata={"indexableText": "alpha beta"},
            uploaded_at=created_at,
        )
        task = await repositories.document_index_tasks.create_task(
            owner_user_id="user-a",
            task_id="index-task-1",
            knowledge_base_id="kb-user-a",
            document_id="doc-1",
            status="pending",
            created_at=created_at,
        )
        running = await repositories.document_index_tasks.mark_running(
            owner_user_id="user-a",
            task_id=task.id,
            started_at=created_at + timedelta(seconds=1),
        )
        failed = await repositories.document_index_tasks.mark_failed(
            owner_user_id="user-a",
            task_id=task.id,
            failure_reason="embedding unavailable",
            completed_at=created_at + timedelta(seconds=2),
        )
        retry = await repositories.document_index_tasks.create_retry(
            owner_user_id="user-a",
            task_id="index-task-2",
            retry_of_task_id=task.id,
            created_at=created_at + timedelta(seconds=3),
        )
        by_document = await repositories.document_index_tasks.list_tasks_for_document(
            owner_user_id="user-a",
            knowledge_base_id="kb-user-a",
            document_id="doc-1",
        )
        cross_tenant = await repositories.document_index_tasks.get_task(
            owner_user_id="user-b",
            task_id=task.id,
        )
    finally:
        await engine.dispose()

    assert task.status == "pending"
    assert running is not None
    assert running.status == "running"
    assert failed is not None
    assert failed.status == "failed"
    assert failed.failure_reason == "embedding unavailable"
    assert retry.retry_of_task_id == task.id
    assert retry.knowledge_base_id == "kb-user-a"
    assert retry.document_id == "doc-1"
    assert [item.id for item in by_document] == ["index-task-1", "index-task-2"]
    assert cross_tenant is None


def test_repository_boundary_exposes_protocols_and_records_only() -> None:
    assert inspect.isclass(ChatMemoryRepository)
    assert all(
        is_dataclass(record_type)
        for record_type in [
            ChatSessionRecord,
            ChatMessageRecord,
            KnowledgeDocumentRecord,
            DocumentIndexTaskRecord,
            DiagnosticTaskRecord,
            DiagnosticReportRecord,
            ToolCallAuditRecord,
            GraphCheckpointRecord,
        ]
    )
    assert all(
        not hasattr(record_type, "__table__")
        for record_type in [
            ChatSessionRecord,
            ChatMessageRecord,
            KnowledgeDocumentRecord,
            DocumentIndexTaskRecord,
            DiagnosticTaskRecord,
            DiagnosticReportRecord,
            ToolCallAuditRecord,
            GraphCheckpointRecord,
        ]
    )

    repository_source = inspect.getsource(repositories_module)
    assert "sqlalchemy" not in repository_source.lower()


@pytest.mark.asyncio
async def test_sqlite_repository_bundle_can_be_injected(migrated_database_url: str) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
    finally:
        await engine.dispose()

    assert isinstance(repositories.chat, SQLiteChatMemoryRepository)
    assert isinstance(repositories.documents, SQLiteKnowledgeDocumentRepository)
    assert repositories.document_index_tasks is not None
    assert isinstance(repositories.diagnostics, SQLiteDiagnosticMemoryRepository)
    assert isinstance(repositories.chat_prompts, SQLiteUserChatPromptRepository)
    assert isinstance(repositories.chat_skills, SQLiteUserChatSkillRepository)


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "memory.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"
