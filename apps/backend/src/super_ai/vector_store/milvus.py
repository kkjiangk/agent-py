"""Milvus vector store implementation with explicit connection lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from importlib import import_module
from time import monotonic
from typing import Any, Protocol, cast

from super_ai.memory.vector_scope import build_milvus_tenant_filter, build_vector_chunk_metadata

from .config import MilvusVectorStoreSettings, load_milvus_vector_store_settings
from .schema import (
    OUTPUT_FIELDS,
    VECTOR_FIELD,
    MilvusCollectionSchemaDefinition,
    MilvusIndexDefinition,
    build_chunk_collection_schema,
    build_index_definitions,
)


class MilvusIndexParamsProtocol(Protocol):
    """Small protocol for PyMilvus index parameter builders."""

    def add_index(self, **kwargs: object) -> None:
        """Add an index definition."""
        ...


class MilvusQueryIteratorProtocol(Protocol):
    """Small protocol for paged scalar queries."""

    def next(self) -> Sequence[Mapping[str, object]]:
        """Return the next entity batch or an empty sequence."""
        ...

    def close(self) -> None:
        """Release iterator resources."""
        ...


class MilvusClientProtocol(Protocol):
    """Minimal MilvusClient surface used by the backend."""

    def has_collection(self, collection_name: str, **kwargs: object) -> bool:
        """Return whether the target collection exists."""
        ...

    def list_collections(self, **kwargs: object) -> Sequence[str]:
        """List available collections."""
        ...

    def prepare_index_params(self) -> MilvusIndexParamsProtocol:
        """Create a new index params builder."""
        ...

    def create_collection(
        self,
        *,
        collection_name: str,
        schema: object,
        index_params: MilvusIndexParamsProtocol,
        **kwargs: object,
    ) -> object:
        """Create a collection."""
        ...

    def create_index(
        self,
        *,
        collection_name: str,
        index_params: MilvusIndexParamsProtocol,
        **kwargs: object,
    ) -> object:
        """Create or ensure collection indexes."""
        ...

    def load_collection(self, *, collection_name: str, **kwargs: object) -> object:
        """Load a collection for search."""
        ...

    def insert(
        self,
        *,
        collection_name: str,
        data: list[dict[str, object]],
        **kwargs: object,
    ) -> object:
        """Insert entities into a collection."""
        ...

    def search(self, **kwargs: object) -> Sequence[Sequence[Mapping[str, object]]]:
        """Search vectors with optional scalar filters."""
        ...

    def query_iterator(self, **kwargs: object) -> MilvusQueryIteratorProtocol:
        """Create an iterator over scalar-filtered entities."""
        ...

    def delete(self, **kwargs: object) -> object:
        """Delete entities by scalar filter."""
        ...


ClientFactory = Callable[[MilvusVectorStoreSettings], MilvusClientProtocol]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class MilvusHealthCheckResult:
    """Secret-safe Milvus readiness result."""

    ok: bool
    uri: str
    collection_name: str
    latency_ms: float
    error: str | None = None


@dataclass(frozen=True, slots=True)
class VectorChunkRecord:
    """Knowledge base chunk to persist in Milvus."""

    chunk_id: str
    document_id: str
    knowledge_base_id: str
    owner_user_id: str
    tenant_id: str
    content: str
    vector: Sequence[float]
    metadata: Mapping[str, object] = field(default_factory=lambda: {})
    source: str = ""
    created_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, slots=True)
class VectorSearchResult:
    """Tenant-scoped vector search hit returned to retrieval code."""

    chunk_id: str
    document_id: str
    knowledge_base_id: str
    owner_user_id: str
    tenant_id: str
    content: str
    source: str
    created_at: int
    metadata: Mapping[str, object]
    score: float


@dataclass(frozen=True, slots=True)
class StoredVectorChunk:
    """Scalar chunk data loaded without its vector for lexical retrieval."""

    chunk_id: str
    document_id: str
    knowledge_base_id: str
    owner_user_id: str
    tenant_id: str
    content: str
    source: str
    created_at: int
    metadata: Mapping[str, object]


class MilvusConnectionManager:
    """Create and reuse a Milvus client only when explicitly requested."""

    def __init__(
        self,
        *,
        settings: MilvusVectorStoreSettings,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory or _create_milvus_client
        self._client: MilvusClientProtocol | None = None

    def connect(self) -> MilvusClientProtocol:
        """Create the client on first explicit use and return it."""
        if self._client is None:
            self._client = self._client_factory(self._settings)
        return self._client


class MilvusVectorStore:
    """Repository-style boundary for Milvus chunk vectors."""

    def __init__(
        self,
        *,
        settings: MilvusVectorStoreSettings,
        connection_manager: MilvusConnectionManager | None = None,
    ) -> None:
        self._settings = settings
        self._connection_manager = connection_manager or MilvusConnectionManager(settings=settings)

    @property
    def settings(self) -> MilvusVectorStoreSettings:
        """Return immutable vector store settings."""
        return self._settings

    def initialize(self) -> None:
        """Create or reuse the collection, ensure indexes, and load it."""
        client = self._connection_manager.connect()
        index_params = _build_milvus_index_params(client, build_index_definitions(self._settings))
        if not client.has_collection(
            self._settings.collection_name,
            timeout=self._settings.timeout_seconds,
        ):
            client.create_collection(
                collection_name=self._settings.collection_name,
                schema=_build_pymilvus_schema(build_chunk_collection_schema(self._settings)),
                index_params=index_params,
                timeout=self._settings.timeout_seconds,
            )
        else:
            client.create_index(
                collection_name=self._settings.collection_name,
                index_params=index_params,
                timeout=self._settings.timeout_seconds,
            )
        client.load_collection(
            collection_name=self._settings.collection_name,
            timeout=self._settings.timeout_seconds,
        )

    def health_check(self) -> MilvusHealthCheckResult:
        """Return a readiness result without leaking transport internals."""
        started_at = monotonic()
        try:
            client = self._connection_manager.connect()
            client.list_collections(timeout=self._settings.timeout_seconds)
        except Exception as exc:
            return MilvusHealthCheckResult(
                ok=False,
                uri=self._settings.uri,
                collection_name=self._settings.collection_name,
                latency_ms=_elapsed_ms(started_at),
                error=_safe_error_message(exc),
            )

        return MilvusHealthCheckResult(
            ok=True,
            uri=self._settings.uri,
            collection_name=self._settings.collection_name,
            latency_ms=_elapsed_ms(started_at),
        )

    def insert_chunks(self, chunks: Sequence[VectorChunkRecord]) -> None:
        """Insert chunk vectors after expanding scalar and metadata ownership fields."""
        if not chunks:
            return
        client = self._connection_manager.connect()
        client.insert(
            collection_name=self._settings.collection_name,
            data=[self._chunk_to_entity(chunk) for chunk in chunks],
            timeout=self._settings.timeout_seconds,
        )

    def search_chunks(
        self,
        *,
        query_vector: Sequence[float],
        tenant_id: str,
        knowledge_base_ids: Sequence[str],
        limit: int,
    ) -> list[VectorSearchResult]:
        """Search chunk vectors while applying tenant and knowledge-base filters."""
        if not knowledge_base_ids:
            return []
        client = self._connection_manager.connect()
        search_result = client.search(
            collection_name=self._settings.collection_name,
            data=[list(query_vector)],
            anns_field=VECTOR_FIELD,
            filter=build_milvus_tenant_filter(
                tenant_id=tenant_id,
                knowledge_base_ids=knowledge_base_ids,
            ),
            limit=limit,
            search_params={
                "metric_type": self._settings.metric_type,
                "params": dict(self._settings.search_params),
            },
            output_fields=list(OUTPUT_FIELDS),
            timeout=self._settings.timeout_seconds,
        )
        return [_search_hit_to_result(hit) for result_set in search_result for hit in result_set]

    def list_chunks(
        self,
        *,
        tenant_id: str,
        knowledge_base_ids: Sequence[str],
    ) -> list[StoredVectorChunk]:
        """List scalar chunk data within an explicit tenant and knowledge-base scope."""
        if not knowledge_base_ids:
            return []
        client = self._connection_manager.connect()
        iterator = client.query_iterator(
            collection_name=self._settings.collection_name,
            batch_size=1000,
            limit=-1,
            filter=build_milvus_tenant_filter(
                tenant_id=tenant_id,
                knowledge_base_ids=knowledge_base_ids,
            ),
            output_fields=list(OUTPUT_FIELDS),
            timeout=self._settings.timeout_seconds,
        )
        chunks: list[StoredVectorChunk] = []
        try:
            while batch := iterator.next():
                chunks.extend(_entity_to_stored_chunk(entity) for entity in batch)
        finally:
            iterator.close()
        return chunks

    def delete_document_chunks(
        self,
        *,
        tenant_id: str,
        knowledge_base_id: str,
        document_id: str,
    ) -> None:
        """Delete all chunks for a scoped document."""
        if not tenant_id or not knowledge_base_id or not document_id:
            raise ValueError("tenant_id, knowledge_base_id, and document_id are required")
        client = self._connection_manager.connect()
        client.delete(
            collection_name=self._settings.collection_name,
            filter=(
                f'tenantId == "{tenant_id}" && '
                f'knowledgeBaseId == "{knowledge_base_id}" && '
                f'documentId == "{document_id}"'
            ),
            timeout=self._settings.timeout_seconds,
        )

    def _chunk_to_entity(self, chunk: VectorChunkRecord) -> dict[str, object]:
        if len(chunk.vector) != self._settings.vector_dimension:
            raise ValueError(
                f"Chunk vector dimension {len(chunk.vector)} does not match "
                f"configured dimension {self._settings.vector_dimension}"
            )
        metadata: dict[str, object] = dict(chunk.metadata)
        metadata.update(
            build_vector_chunk_metadata(
                owner_user_id=chunk.owner_user_id,
                tenant_id=chunk.tenant_id,
                knowledge_base_id=chunk.knowledge_base_id,
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
            )
        )
        return {
            "chunkId": chunk.chunk_id,
            "documentId": chunk.document_id,
            "knowledgeBaseId": chunk.knowledge_base_id,
            "ownerUserId": chunk.owner_user_id,
            "tenantId": chunk.tenant_id,
            "content": chunk.content,
            "source": chunk.source,
            "createdAt": _to_epoch_millis(chunk.created_at),
            "metadata": metadata,
            "vector": list(chunk.vector),
        }


def build_default_milvus_vector_store(config_path: str | None = None) -> MilvusVectorStore:
    """Build the default Milvus vector store without connecting to Milvus."""
    settings = load_milvus_vector_store_settings(config_path=config_path)
    return MilvusVectorStore(settings=settings)


def _build_milvus_index_params(
    client: MilvusClientProtocol,
    index_definitions: Sequence[MilvusIndexDefinition],
) -> MilvusIndexParamsProtocol:
    index_params = client.prepare_index_params()
    for definition in index_definitions:
        kwargs: dict[str, object] = {
            "field_name": definition.field_name,
            "index_type": definition.index_type,
        }
        if definition.metric_type is not None:
            kwargs["metric_type"] = definition.metric_type
        if definition.params is not None:
            kwargs["params"] = dict(definition.params)
        index_params.add_index(**kwargs)
    return index_params


def _build_pymilvus_schema(definition: MilvusCollectionSchemaDefinition) -> object:
    pymilvus = import_module("pymilvus")
    milvus_client: Any = pymilvus.MilvusClient
    data_type: Any = pymilvus.DataType
    schema = milvus_client.create_schema(
        auto_id=definition.auto_id,
        enable_dynamic_field=definition.enable_dynamic_field,
    )
    for field_definition in definition.fields:
        kwargs: dict[str, object] = {
            "field_name": field_definition.name,
            "datatype": getattr(data_type, field_definition.data_type),
        }
        if field_definition.is_primary:
            kwargs["is_primary"] = True
        if field_definition.max_length is not None:
            kwargs["max_length"] = field_definition.max_length
        if field_definition.dimension is not None:
            kwargs["dim"] = field_definition.dimension
        schema.add_field(**kwargs)
    return schema


def _create_milvus_client(settings: MilvusVectorStoreSettings) -> MilvusClientProtocol:
    pymilvus = import_module("pymilvus")
    milvus_client: Any = pymilvus.MilvusClient
    return cast(
        MilvusClientProtocol,
        milvus_client(uri=settings.uri, timeout=settings.timeout_seconds),
    )


def _search_hit_to_result(hit: Mapping[str, object]) -> VectorSearchResult:
    entity = _mapping(hit.get("entity"))
    return VectorSearchResult(
        chunk_id=_string(entity, "chunkId"),
        document_id=_string(entity, "documentId"),
        knowledge_base_id=_string(entity, "knowledgeBaseId"),
        owner_user_id=_string(entity, "ownerUserId"),
        tenant_id=_string(entity, "tenantId"),
        content=_string(entity, "content"),
        source=_string(entity, "source"),
        created_at=_int(entity, "createdAt"),
        metadata=_mapping(entity.get("metadata")),
        score=_float(hit.get("distance")),
    )


def _entity_to_stored_chunk(entity: Mapping[str, object]) -> StoredVectorChunk:
    return StoredVectorChunk(
        chunk_id=_string(entity, "chunkId"),
        document_id=_string(entity, "documentId"),
        knowledge_base_id=_string(entity, "knowledgeBaseId"),
        owner_user_id=_string(entity, "ownerUserId"),
        tenant_id=_string(entity, "tenantId"),
        content=_string(entity, "content"),
        source=_string(entity, "source"),
        created_at=_int(entity, "createdAt"),
        metadata=_mapping(entity.get("metadata")),
    )


def _mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return {}


def _string(entity: Mapping[str, object], key: str) -> str:
    value = entity.get(key)
    if isinstance(value, str):
        return value
    return ""


def _int(entity: Mapping[str, object], key: str) -> int:
    value = entity.get(key)
    if isinstance(value, int):
        return value
    return 0


def _float(value: object) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _to_epoch_millis(value: datetime) -> int:
    aware_value = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return int(aware_value.timestamp() * 1000)


def _elapsed_ms(started_at: float) -> float:
    return round((monotonic() - started_at) * 1000, 3)


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__
