from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config

from super_ai.api.app import create_app
from super_ai.vector_store import MilvusHealthCheckResult, VectorChunkRecord


class FakeEmbeddingModel:
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _text in texts]


class FakeIndexVectorStore:
    def health_check(self) -> MilvusHealthCheckResult:
        return MilvusHealthCheckResult(
            ok=True,
            uri="http://milvus:19530",
            collection_name="knowledge_chunks",
            latency_ms=1.0,
        )

    def delete_document_chunks(
        self,
        *,
        tenant_id: str,
        knowledge_base_id: str,
        document_id: str,
    ) -> None:
        return None

    def insert_chunks(self, chunks: Sequence[VectorChunkRecord]) -> None:
        return None


class FakeIndexTaskScheduler:
    def __init__(self) -> None:
        self.scheduled: list[dict[str, str]] = []

    def schedule(self, *, owner_user_id: str, task_id: str) -> None:
        self.scheduled.append({"owner_user_id": owner_user_id, "task_id": task_id})


@pytest.mark.asyncio
async def test_document_index_task_api_creates_reads_and_retries_scoped_tasks(
    migrated_database_url: str,
) -> None:
    scheduler = FakeIndexTaskScheduler()
    app = create_app(
        database_url=migrated_database_url,
        vector_store=FakeIndexVectorStore(),
        embedding_model=FakeEmbeddingModel(),
        index_task_scheduler=scheduler,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user = await _register(client, "index@example.com", "Indexer")
        kb_id = f"kb_{user['user']['id']}"
        headers = _auth_headers(user["accessToken"])
        upload = await client.post(
            f"/knowledge-bases/{kb_id}/documents",
            headers=headers,
            files={"file": ("runbook.md", b"alpha beta gamma", "text/markdown")},
        )
        document_id = upload.json()["data"]["document"]["id"]

        create_response = await client.post(
            f"/knowledge-bases/{kb_id}/documents/{document_id}/index-tasks",
            headers=headers,
        )
        task = create_response.json()["data"]["task"]
        read_response = await client.get(
            f"/knowledge-bases/{kb_id}/documents/{document_id}/index-tasks/{task['id']}",
            headers=headers,
        )
        await app.state.memory_repositories.document_index_tasks.mark_failed(
            owner_user_id=user["user"]["id"],
            task_id=task["id"],
            failure_reason="embedding unavailable",
        )
        retry_response = await client.post(
            f"/knowledge-bases/{kb_id}/documents/{document_id}/index-tasks/{task['id']}:retry",
            headers=headers,
        )

    assert create_response.status_code == 202
    assert task["ownerUserId"] == user["user"]["id"]
    assert task["knowledgeBaseId"] == kb_id
    assert task["documentId"] == document_id
    assert task["status"] == "pending"
    assert create_response.json()["data"]["scheduled"] is True
    assert read_response.status_code == 200
    assert read_response.json()["data"]["id"] == task["id"]
    assert retry_response.status_code == 202
    assert retry_response.json()["data"]["retriedFromTaskId"] == task["id"]
    assert retry_response.json()["data"]["task"]["retryOfTaskId"] == task["id"]
    assert len(scheduler.scheduled) == 2


@pytest.mark.asyncio
async def test_document_index_task_api_rejects_cross_tenant_access(
    migrated_database_url: str,
) -> None:
    app = create_app(
        database_url=migrated_database_url,
        vector_store=FakeIndexVectorStore(),
        embedding_model=FakeEmbeddingModel(),
        index_task_scheduler=FakeIndexTaskScheduler(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user_a = await _register(client, "owner@example.com", "Owner")
        user_b = await _register(client, "other@example.com", "Other")
        kb_a = f"kb_{user_a['user']['id']}"
        upload = await client.post(
            f"/knowledge-bases/{kb_a}/documents",
            headers=_auth_headers(user_a["accessToken"]),
            files={"file": ("runbook.md", b"alpha beta", "text/markdown")},
        )
        document_id = upload.json()["data"]["document"]["id"]

        response = await client.post(
            f"/knowledge-bases/{kb_a}/documents/{document_id}/index-tasks",
            headers=_auth_headers(user_b["accessToken"]),
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "AUTH_FORBIDDEN"


async def _register(client: httpx.AsyncClient, email: str, display_name: str) -> dict[str, Any]:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "displayName": display_name,
            "password": "correct horse battery staple",
        },
    )
    return response.json()["data"]


def _auth_headers(token: object) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "document-indexing-api.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"
