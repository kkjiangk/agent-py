from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from super_ai.documents.indexing import DocumentIndexingService, chunk_document_text
from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.sqlite import create_sqlite_memory_repositories
from super_ai.vector_store import VectorChunkRecord


class FakeEmbeddingModel:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.inputs: list[list[str]] = []

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        self.inputs.append(texts)
        if self.error is not None:
            raise self.error
        return [[float(index), 0.1, 0.2] for index, _text in enumerate(texts)]


class FakeIndexVectorStore:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.initialized_calls = 0
        self.deleted_documents: list[dict[str, str]] = []
        self.inserted_chunks: list[VectorChunkRecord] = []

    def initialize(self) -> None:
        self.initialized_calls += 1

    def delete_document_chunks(
        self,
        *,
        tenant_id: str,
        knowledge_base_id: str,
        document_id: str,
    ) -> None:
        self.deleted_documents.append(
            {
                "tenant_id": tenant_id,
                "knowledge_base_id": knowledge_base_id,
                "document_id": document_id,
            }
        )

    def insert_chunks(self, chunks: Sequence[VectorChunkRecord]) -> None:
        if self.error is not None:
            raise self.error
        self.inserted_chunks = list(chunks)


def test_chunk_document_text_is_deterministic_and_preserves_order() -> None:
    chunks = chunk_document_text(
        "alpha beta gamma delta epsilon",
        chunk_size=16,
        chunk_overlap=4,
    )

    assert [chunk.index for chunk in chunks] == [0, 1]
    assert chunks[0].content == "alpha beta gamma"
    assert chunks[1].content == "delta epsilon"
    assert chunks[0].metadata["start"] == 0
    assert chunks[1].metadata["chunkIndex"] == 1


def test_chunk_document_text_supports_fixed_heading_and_paragraph_strategies() -> None:
    fixed = chunk_document_text(
        "abcdefghij",
        strategy="fixed-character",
        chunk_size=5,
        chunk_overlap=2,
    )
    headings = chunk_document_text(
        "# 网络\n第一章节\n\n## 数据库\n第二章节",
        strategy="markdown-heading",
        chunk_size=12,
        chunk_overlap=0,
    )
    paragraphs = chunk_document_text(
        "第一段落内容。\n\n第二段落内容。",
        strategy="paragraph",
        chunk_size=10,
        chunk_overlap=0,
    )

    assert [chunk.content for chunk in fixed] == ["abcde", "defgh", "ghij"]
    assert [chunk.heading_path for chunk in headings] == ["网络", "网络 / 数据库"]
    assert [chunk.content for chunk in paragraphs] == ["第一段落内容。", "第二段落内容。"]


@pytest.mark.asyncio
async def test_document_indexing_service_writes_scoped_chunks_and_marks_success(
    migrated_database_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    logging.getLogger("super_ai.documents.indexing").disabled = False
    caplog.set_level(logging.INFO, logger="super_ai.documents.indexing")
    engine = create_memory_engine(migrated_database_url)
    vector_store = FakeIndexVectorStore()
    embedding_model = FakeEmbeddingModel()
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        document = await repositories.documents.create_document(
            owner_user_id="user-a",
            document_id="doc-1",
            knowledge_base_id="kb-user-a",
            filename="runbook.md",
            size_bytes=64,
            mime_type="text/markdown",
            content_hash="sha256:abc",
            metadata={"indexableText": "alpha beta gamma delta epsilon", "kind": "sop"},
        )
        task = await repositories.document_index_tasks.create_task(
            owner_user_id="user-a",
            task_id="index-task-1",
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
        )
        service = DocumentIndexingService(
            repositories=repositories,
            embedding_model=embedding_model,
            vector_store=vector_store,
            chunk_size=16,
            chunk_overlap=4,
        )

        result = await service.run_task(owner_user_id="user-a", task_id=task.id)
        updated_task = await repositories.document_index_tasks.get_task(
            owner_user_id="user-a",
            task_id=task.id,
        )
        updated_document = await repositories.documents.get_document(
            owner_user_id="user-a",
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
        )
    finally:
        await engine.dispose()

    assert result.status == "succeeded"
    assert updated_task is not None
    assert updated_task.status == "succeeded"
    assert updated_task.failure_reason is None
    assert updated_document is not None
    assert updated_document.index_status == "indexed"
    assert embedding_model.inputs == [["alpha beta gamma", "delta epsilon"]]
    assert vector_store.initialized_calls == 1
    assert vector_store.deleted_documents == [
        {
            "tenant_id": "user-a",
            "knowledge_base_id": "kb-user-a",
            "document_id": "doc-1",
        }
    ]
    assert [chunk.chunk_id for chunk in vector_store.inserted_chunks] == [
        "doc-1_chunk_0000",
        "doc-1_chunk_0001",
    ]
    assert all(chunk.owner_user_id == "user-a" for chunk in vector_store.inserted_chunks)
    assert all(chunk.tenant_id == "user-a" for chunk in vector_store.inserted_chunks)
    assert vector_store.inserted_chunks[0].metadata["ownerUserId"] == "user-a"
    assert vector_store.inserted_chunks[0].metadata["chunkIndex"] == 0
    assert vector_store.inserted_chunks[0].metadata["knowledgeType"] == "sop"
    events = [
        json.loads(record.message) for record in caplog.records if record.message.startswith("{")
    ]
    assert {event["event"] for event in events} == {
        "index.task.started",
        "index.task.completed",
    }
    completed = next(event for event in events if event["event"] == "index.task.completed")
    assert completed["taskId"] == task.id
    assert completed["documentId"] == document.id
    assert completed["chunkCount"] == 2
    assert "alpha beta gamma" not in "\n".join(record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_document_indexing_service_indexes_more_than_ten_chunks(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    vector_store = FakeIndexVectorStore()
    embedding_model = FakeEmbeddingModel()
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        document = await repositories.documents.create_document(
            owner_user_id="user-a",
            document_id="doc-large",
            knowledge_base_id="kb-user-a",
            filename="large.md",
            size_bytes=11,
            mime_type="text/markdown",
            content_hash="sha256:large",
            metadata={
                "indexableText": "abcdefghijk",
                "chunking": {
                    "strategy": "fixed-character",
                    "maxCharacters": 1,
                    "overlapCharacters": 0,
                },
            },
        )
        task = await repositories.document_index_tasks.create_task(
            owner_user_id="user-a",
            task_id="index-task-large",
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
        )
        service = DocumentIndexingService(
            repositories=repositories,
            embedding_model=embedding_model,
            vector_store=vector_store,
        )

        result = await service.run_task(owner_user_id="user-a", task_id=task.id)
    finally:
        await engine.dispose()

    assert result.status == "succeeded"
    assert len(embedding_model.inputs[0]) == 11
    assert [chunk.content for chunk in vector_store.inserted_chunks] == list("abcdefghijk")


@pytest.mark.asyncio
async def test_document_indexing_service_records_safe_failure_reason(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        document = await repositories.documents.create_document(
            owner_user_id="user-a",
            document_id="doc-empty",
            knowledge_base_id="kb-user-a",
            filename="empty.md",
            size_bytes=0,
            mime_type="text/markdown",
            content_hash="sha256:empty",
            metadata={"indexableText": "   "},
        )
        task = await repositories.document_index_tasks.create_task(
            owner_user_id="user-a",
            task_id="index-task-empty",
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
        )
        service = DocumentIndexingService(
            repositories=repositories,
            embedding_model=FakeEmbeddingModel(),
            vector_store=FakeIndexVectorStore(),
        )

        result = await service.run_task(owner_user_id="user-a", task_id=task.id)
        updated_document = await repositories.documents.get_document(
            owner_user_id="user-a",
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
        )
    finally:
        await engine.dispose()

    assert result.status == "failed"
    assert result.failure_reason == "Document has no indexable text."
    assert updated_document is not None
    assert updated_document.index_status == "failed"


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "document-indexing.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"
