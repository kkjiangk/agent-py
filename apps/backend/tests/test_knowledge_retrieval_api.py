from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config

from super_ai.api.app import create_app
from super_ai.vector_store import MilvusHealthCheckResult, VectorSearchResult


class FakeEmbeddingModel:
    def __init__(self) -> None:
        self.inputs: list[list[str]] = []

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        self.inputs.append(texts)
        return [[0.1, 0.2, 0.3] for _text in texts]


class FakeRetrievalVectorStore:
    def __init__(self) -> None:
        self.searches: list[dict[str, object]] = []

    def health_check(self) -> MilvusHealthCheckResult:
        return MilvusHealthCheckResult(
            ok=True,
            uri="http://milvus:19530",
            collection_name="knowledge_chunks",
            latency_ms=1.0,
        )

    def search_chunks(
        self,
        *,
        query_vector: Sequence[float],
        tenant_id: str,
        knowledge_base_ids: Sequence[str],
        limit: int,
    ) -> list[VectorSearchResult]:
        self.searches.append(
            {
                "query_vector": list(query_vector),
                "tenant_id": tenant_id,
                "knowledge_base_ids": list(knowledge_base_ids),
                "limit": limit,
            }
        )
        return []


@pytest.mark.asyncio
async def test_chat_session_creation_does_not_run_retrieval_as_fixed_prestep(
    migrated_database_url: str,
) -> None:
    embedding_model = FakeEmbeddingModel()
    vector_store = FakeRetrievalVectorStore()
    transport = httpx.ASGITransport(
        app=create_app(
            database_url=migrated_database_url,
            vector_store=vector_store,
            embedding_model=embedding_model,
        )
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user = await _register(client, "chat@example.com", "Chat User")
        response = await client.post(
            "/chat/sessions",
            headers=_auth_headers(user["accessToken"]),
            json={"title": "Ask without retrieval prefetch"},
        )

    assert response.status_code == 201
    assert embedding_model.inputs == []
    assert vector_store.searches == []


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
    database_path = tmp_path / "knowledge-retrieval-api.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"
