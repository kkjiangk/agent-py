from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

import pytest


def test_importing_vector_store_package_does_not_import_pymilvus() -> None:
    sys.modules.pop("super_ai.vector_store", None)
    sys.modules.pop("super_ai.vector_store.milvus", None)
    sys.modules.pop("pymilvus", None)

    importlib.import_module("super_ai.vector_store")

    assert "pymilvus" not in sys.modules


def test_default_settings_and_explicit_project_config(tmp_path: Path) -> None:
    from super_ai.vector_store import load_milvus_vector_store_settings

    settings = load_milvus_vector_store_settings()

    assert settings.uri == "http://localhost:19530"
    assert settings.collection_name == "knowledge_chunks"
    assert settings.vector_dimension == 1024
    assert settings.index_type == "HNSW"
    assert settings.metric_type == "COSINE"
    assert settings.index_params == {"M": 16, "efConstruction": 200}
    assert settings.search_params == {"ef": 64}

    config_path = tmp_path / "project.json"
    config_path.write_text(
        json.dumps(
            {
                "vectorStore": {
                    "uri": "http://milvus:19530",
                    "collectionName": "tenant_chunks",
                    "vectorDimension": 768,
                    "indexType": "IVF_FLAT",
                    "metricType": "IP",
                    "timeoutSeconds": 3.5,
                    "indexParams": {"nlist": 128},
                    "searchParams": {"nprobe": 16},
                }
            }
        ),
        encoding="utf-8",
    )
    overridden = load_milvus_vector_store_settings(config_path=config_path)

    assert overridden.uri == "http://milvus:19530"
    assert overridden.collection_name == "tenant_chunks"
    assert overridden.vector_dimension == 768
    assert overridden.index_type == "IVF_FLAT"
    assert overridden.metric_type == "IP"
    assert overridden.timeout_seconds == 3.5
    assert overridden.index_params == {"nlist": 128}
    assert overridden.search_params == {"nprobe": 16}


def test_collection_schema_contains_required_fields_and_dimension() -> None:
    from super_ai.vector_store import MilvusVectorStoreSettings, build_chunk_collection_schema

    schema = build_chunk_collection_schema(MilvusVectorStoreSettings(vector_dimension=384))
    fields = {field.name: field for field in schema.fields}

    assert set(fields) == {
        "chunkId",
        "documentId",
        "knowledgeBaseId",
        "ownerUserId",
        "tenantId",
        "content",
        "source",
        "createdAt",
        "metadata",
        "vector",
    }
    assert fields["chunkId"].is_primary is True
    assert fields["chunkId"].data_type == "VARCHAR"
    assert fields["metadata"].data_type == "JSON"
    assert fields["createdAt"].data_type == "INT64"
    assert fields["vector"].data_type == "FLOAT_VECTOR"
    assert fields["vector"].dimension == 384


def test_connection_manager_creates_client_only_when_explicitly_connected() -> None:
    from super_ai.vector_store import MilvusConnectionManager, MilvusVectorStoreSettings

    created: list[MilvusVectorStoreSettings] = []

    def client_factory(settings: MilvusVectorStoreSettings) -> FakeMilvusClient:
        created.append(settings)
        return FakeMilvusClient()

    settings = MilvusVectorStoreSettings(uri="http://milvus:19530")
    manager = MilvusConnectionManager(settings=settings, client_factory=client_factory)

    assert created == []

    first_client = manager.connect()
    second_client = manager.connect()

    assert first_client is second_client
    assert created == [settings]


def test_initialize_creates_missing_collection_with_indexes_and_loads() -> None:
    from super_ai.vector_store import (
        MilvusConnectionManager,
        MilvusVectorStore,
        MilvusVectorStoreSettings,
    )

    fake_client = FakeMilvusClient(collection_exists=False)
    settings = MilvusVectorStoreSettings()
    store = MilvusVectorStore(
        settings=settings,
        connection_manager=MilvusConnectionManager(
            settings=settings,
            client_factory=lambda _settings: fake_client,
        ),
    )

    store.initialize()

    assert fake_client.created_collection == "knowledge_chunks"
    assert fake_client.created_schema is not None
    assert fake_client.load_calls == ["knowledge_chunks"]
    assert fake_client.created_collection_indexes.field_names == [
        "tenantId",
        "knowledgeBaseId",
        "ownerUserId",
        "documentId",
        "createdAt",
        "vector",
    ]
    assert fake_client.created_collection_indexes.indexes[-1] == {
        "field_name": "vector",
        "index_type": "HNSW",
        "metric_type": "COSINE",
        "params": {"M": 16, "efConstruction": 200},
    }


def test_initialize_existing_collection_ensures_indexes_and_loads() -> None:
    from super_ai.vector_store import (
        MilvusConnectionManager,
        MilvusVectorStore,
        MilvusVectorStoreSettings,
    )

    fake_client = FakeMilvusClient(collection_exists=True)
    settings = MilvusVectorStoreSettings()
    store = MilvusVectorStore(
        settings=settings,
        connection_manager=MilvusConnectionManager(
            settings=settings,
            client_factory=lambda _settings: fake_client,
        ),
    )

    store.initialize()

    assert fake_client.created_collection is None
    assert fake_client.created_index_params is not None
    assert fake_client.created_index_params.field_names[-1] == "vector"
    assert fake_client.load_calls == ["knowledge_chunks"]


def test_health_check_returns_safe_results() -> None:
    from super_ai.vector_store import (
        MilvusConnectionManager,
        MilvusVectorStore,
        MilvusVectorStoreSettings,
    )

    settings = MilvusVectorStoreSettings()
    healthy_store = MilvusVectorStore(
        settings=settings,
        connection_manager=MilvusConnectionManager(
            settings=settings,
            client_factory=lambda _settings: FakeMilvusClient(),
        ),
    )

    healthy = healthy_store.health_check()

    assert healthy.ok is True
    assert healthy.collection_name == "knowledge_chunks"
    assert healthy.error is None

    failing_store = MilvusVectorStore(
        settings=settings,
        connection_manager=MilvusConnectionManager(
            settings=settings,
            client_factory=lambda _settings: FakeMilvusClient(error=RuntimeError("boom token")),
        ),
    )

    unhealthy = failing_store.health_check()

    assert unhealthy.ok is False
    assert unhealthy.collection_name == "knowledge_chunks"
    assert unhealthy.error == "boom token"


def test_insert_chunks_expands_scalars_and_metadata() -> None:
    from super_ai.vector_store import (
        MilvusConnectionManager,
        MilvusVectorStore,
        MilvusVectorStoreSettings,
        VectorChunkRecord,
    )

    fake_client = FakeMilvusClient()
    settings = MilvusVectorStoreSettings(vector_dimension=3)
    store = MilvusVectorStore(
        settings=settings,
        connection_manager=MilvusConnectionManager(
            settings=settings,
            client_factory=lambda _settings: fake_client,
        ),
    )
    chunk = VectorChunkRecord(
        chunk_id="chunk_1",
        document_id="doc_1",
        knowledge_base_id="kb_1",
        owner_user_id="user_1",
        tenant_id="tenant_1",
        content="hello",
        vector=[0.1, 0.2, 0.3],
        metadata={"page": 1},
        source="file://doc.md",
        created_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
    )

    store.insert_chunks([chunk])

    assert fake_client.inserted_data == [
        {
            "chunkId": "chunk_1",
            "documentId": "doc_1",
            "knowledgeBaseId": "kb_1",
            "ownerUserId": "user_1",
            "tenantId": "tenant_1",
            "content": "hello",
            "source": "file://doc.md",
            "createdAt": 1783555200000,
            "metadata": {
                "page": 1,
                "ownerUserId": "user_1",
                "tenantId": "tenant_1",
                "knowledgeBaseId": "kb_1",
                "documentId": "doc_1",
                "chunkId": "chunk_1",
            },
            "vector": [0.1, 0.2, 0.3],
        }
    ]


def test_search_chunks_applies_tenant_filter_and_returns_records() -> None:
    from super_ai.vector_store import (
        MilvusConnectionManager,
        MilvusVectorStore,
        MilvusVectorStoreSettings,
    )

    fake_client = FakeMilvusClient(
        search_result=[
            [
                {
                    "id": "chunk_1",
                    "distance": 0.12,
                    "entity": {
                        "chunkId": "chunk_1",
                        "documentId": "doc_1",
                        "knowledgeBaseId": "kb_1",
                        "ownerUserId": "user_1",
                        "tenantId": "tenant_1",
                        "content": "hello",
                        "source": "file://doc.md",
                        "createdAt": 1783555200000,
                        "metadata": {"page": 1},
                    },
                }
            ]
        ]
    )
    settings = MilvusVectorStoreSettings(vector_dimension=3)
    store = MilvusVectorStore(
        settings=settings,
        connection_manager=MilvusConnectionManager(
            settings=settings,
            client_factory=lambda _settings: fake_client,
        ),
    )

    results = store.search_chunks(
        query_vector=[0.1, 0.2, 0.3],
        tenant_id="tenant_1",
        knowledge_base_ids=["kb_1", "kb_2"],
        limit=5,
    )

    assert fake_client.search_kwargs["filter"] == (
        'tenantId == "tenant_1" && knowledgeBaseId in ["kb_1","kb_2"]'
    )
    assert fake_client.search_kwargs["search_params"] == {
        "metric_type": "COSINE",
        "params": {"ef": 64},
    }
    assert fake_client.search_kwargs["output_fields"] == [
        "chunkId",
        "documentId",
        "knowledgeBaseId",
        "ownerUserId",
        "tenantId",
        "content",
        "source",
        "createdAt",
        "metadata",
    ]
    assert results[0].chunk_id == "chunk_1"
    assert results[0].score == 0.12
    assert results[0].metadata == {"page": 1}


def test_list_chunks_iterates_tenant_scoped_scalar_entities() -> None:
    from super_ai.vector_store import (
        MilvusConnectionManager,
        MilvusVectorStore,
        MilvusVectorStoreSettings,
    )

    entity = {
        "chunkId": "chunk_1",
        "documentId": "doc_1",
        "knowledgeBaseId": "kb_1",
        "ownerUserId": "user_1",
        "tenantId": "tenant_1",
        "content": "hello",
        "source": "file://doc.md",
        "createdAt": 1783555200000,
        "metadata": {"page": 1},
    }
    fake_client = FakeMilvusClient(query_batches=[[entity]])
    settings = MilvusVectorStoreSettings()
    store = MilvusVectorStore(
        settings=settings,
        connection_manager=MilvusConnectionManager(
            settings=settings,
            client_factory=lambda _settings: fake_client,
        ),
    )

    chunks = store.list_chunks(
        tenant_id="tenant_1",
        knowledge_base_ids=["kb_1", "kb_2"],
    )

    assert fake_client.query_iterator_kwargs == {
        "collection_name": "knowledge_chunks",
        "batch_size": 1000,
        "limit": -1,
        "filter": 'tenantId == "tenant_1" && knowledgeBaseId in ["kb_1","kb_2"]',
        "output_fields": [
            "chunkId",
            "documentId",
            "knowledgeBaseId",
            "ownerUserId",
            "tenantId",
            "content",
            "source",
            "createdAt",
            "metadata",
        ],
        "timeout": 10.0,
    }
    assert chunks[0].chunk_id == "chunk_1"
    assert chunks[0].metadata == {"page": 1}
    assert fake_client.query_iterator_instance.closed is True


def test_list_chunks_skips_unscoped_query() -> None:
    from super_ai.vector_store import (
        MilvusConnectionManager,
        MilvusVectorStore,
        MilvusVectorStoreSettings,
    )

    fake_client = FakeMilvusClient()
    settings = MilvusVectorStoreSettings()
    store = MilvusVectorStore(
        settings=settings,
        connection_manager=MilvusConnectionManager(
            settings=settings,
            client_factory=lambda _settings: fake_client,
        ),
    )

    assert store.list_chunks(tenant_id="tenant_1", knowledge_base_ids=[]) == []
    assert fake_client.query_iterator_kwargs == {}


def test_delete_document_chunks_applies_scope_filter_and_rejects_empty_scope() -> None:
    from super_ai.vector_store import (
        MilvusConnectionManager,
        MilvusVectorStore,
        MilvusVectorStoreSettings,
    )

    fake_client = FakeMilvusClient()
    settings = MilvusVectorStoreSettings()
    store = MilvusVectorStore(
        settings=settings,
        connection_manager=MilvusConnectionManager(
            settings=settings,
            client_factory=lambda _settings: fake_client,
        ),
    )

    store.delete_document_chunks(
        tenant_id="tenant_1",
        knowledge_base_id="kb_1",
        document_id="doc_1",
    )

    assert fake_client.delete_kwargs == {
        "collection_name": "knowledge_chunks",
        "filter": 'tenantId == "tenant_1" && knowledgeBaseId == "kb_1" && documentId == "doc_1"',
        "timeout": 10.0,
    }

    for tenant_id, knowledge_base_id, document_id in [
        ("", "kb_1", "doc_1"),
        ("tenant_1", "", "doc_1"),
        ("tenant_1", "kb_1", ""),
    ]:
        with pytest.raises(ValueError):
            store.delete_document_chunks(
                tenant_id=tenant_id,
                knowledge_base_id=knowledge_base_id,
                document_id=document_id,
            )


@pytest.mark.asyncio
async def test_ready_endpoint_reports_milvus_readiness_without_startup_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    import super_ai.api.app as api_app
    from super_ai.api.app import create_app
    from super_ai.llm import LlmProvider, LlmReadinessResult
    from super_ai.vector_store import MilvusHealthCheckResult

    class FakeVectorStore:
        def __init__(self) -> None:
            self.health_checks = 0

        def health_check(self) -> MilvusHealthCheckResult:
            self.health_checks += 1
            return MilvusHealthCheckResult(
                ok=True,
                uri="http://milvus:19530",
                collection_name="knowledge_chunks",
                latency_ms=1.0,
            )

    class FakeLlmProvider:
        async def check_readiness(self) -> LlmReadinessResult:
            return LlmReadinessResult(
                ok=True,
                provider="qwen-openai",
                model="qwen-test",
                base_url="https://provider.test/v1",
                latency_ms=1.0,
            )

    class FakeMcpClient:
        async def readiness(self) -> dict[str, object]:
            return {"ok": True, "endpoint": "http://mcp.test/sse", "toolCount": 1}

    def fake_mcp_client(_request: object) -> FakeMcpClient:
        return FakeMcpClient()

    vector_store = FakeVectorStore()
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/health.sqlite3",
        vector_store=vector_store,
        llm_provider=cast(LlmProvider, FakeLlmProvider()),
    )
    monkeypatch.setattr(api_app, "_mcp_client", fake_mcp_client)

    assert vector_store.health_checks == 0

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["status"] == "ready"
    assert payload["data"]["dependencies"]["milvus"] == {
        "ok": True,
        "uri": "http://milvus:19530",
        "collectionName": "knowledge_chunks",
        "latencyMs": 1.0,
        "error": None,
    }
    assert vector_store.health_checks == 1


def test_project_config_contains_milvus_settings() -> None:
    config = json.loads(Path("../../config/project.json").read_text(encoding="utf-8"))
    vector_store = config["vectorStore"]

    assert vector_store["uri"] == "http://localhost:19530"
    assert vector_store["collectionName"] == "knowledge_chunks"
    assert vector_store["vectorDimension"] == 1024


class FakeIndexParams:
    def __init__(self) -> None:
        self.indexes: list[dict[str, object]] = []

    @property
    def field_names(self) -> list[str]:
        return [str(index["field_name"]) for index in self.indexes]

    def add_index(self, **kwargs: object) -> None:
        self.indexes.append(kwargs)


class FakeMilvusClient:
    def __init__(
        self,
        *,
        collection_exists: bool = True,
        error: Exception | None = None,
        search_result: list[list[Mapping[str, object]]] | None = None,
        query_batches: list[list[Mapping[str, object]]] | None = None,
    ) -> None:
        self.collection_exists = collection_exists
        self.error = error
        self.search_result: list[list[Mapping[str, object]]] = search_result or []
        self.created_collection: str | None = None
        self.created_schema: object | None = None
        self.created_collection_indexes = FakeIndexParams()
        self.created_index_params: FakeIndexParams | None = None
        self.load_calls: list[str] = []
        self.inserted_data: list[dict[str, object]] = []
        self.search_kwargs: dict[str, object] = {}
        self.query_iterator_kwargs: dict[str, object] = {}
        self.query_iterator_instance = FakeQueryIterator(query_batches or [])
        self.delete_kwargs: dict[str, object] = {}

    def has_collection(self, collection_name: str, **_kwargs: object) -> bool:
        if self.error is not None:
            raise self.error
        return self.collection_exists

    def list_collections(self, **_kwargs: object) -> list[str]:
        if self.error is not None:
            raise self.error
        return ["knowledge_chunks"]

    def prepare_index_params(self) -> FakeIndexParams:
        return FakeIndexParams()

    def create_collection(
        self,
        *,
        collection_name: str,
        schema: object,
        index_params: object,
        **_kwargs: object,
    ) -> None:
        if not isinstance(index_params, FakeIndexParams):
            raise AssertionError("Expected FakeIndexParams")
        self.created_collection = collection_name
        self.created_schema = schema
        self.created_collection_indexes = index_params

    def create_index(
        self,
        *,
        collection_name: str,
        index_params: object,
        **_kwargs: object,
    ) -> None:
        if not isinstance(index_params, FakeIndexParams):
            raise AssertionError("Expected FakeIndexParams")
        self.created_collection = self.created_collection
        self.created_index_params = index_params

    def load_collection(self, *, collection_name: str, **_kwargs: object) -> None:
        self.load_calls.append(collection_name)

    def insert(
        self,
        *,
        collection_name: str,
        data: list[dict[str, object]],
        **_kwargs: object,
    ) -> None:
        self.inserted_data = data

    def search(self, **kwargs: object) -> list[list[Mapping[str, object]]]:
        self.search_kwargs = dict(kwargs)
        return self.search_result

    def query_iterator(self, **kwargs: object) -> FakeQueryIterator:
        self.query_iterator_kwargs = dict(kwargs)
        return self.query_iterator_instance

    def delete(self, **kwargs: object) -> None:
        self.delete_kwargs = dict(kwargs)


class FakeQueryIterator:
    def __init__(self, batches: list[list[Mapping[str, object]]]) -> None:
        self._batches = iter([*batches, []])
        self.closed = False

    def next(self) -> list[Mapping[str, object]]:
        return next(self._batches)

    def close(self) -> None:
        self.closed = True
