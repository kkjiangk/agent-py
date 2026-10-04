"""Milvus collection schema definitions for knowledge chunk vectors."""

from __future__ import annotations

from dataclasses import dataclass

from super_ai.vector_store.config import MilvusVectorStoreSettings

CHUNK_ID_FIELD = "chunkId"
DOCUMENT_ID_FIELD = "documentId"
KNOWLEDGE_BASE_ID_FIELD = "knowledgeBaseId"
OWNER_USER_ID_FIELD = "ownerUserId"
TENANT_ID_FIELD = "tenantId"
CONTENT_FIELD = "content"
SOURCE_FIELD = "source"
CREATED_AT_FIELD = "createdAt"
METADATA_FIELD = "metadata"
VECTOR_FIELD = "vector"

SCALAR_FILTER_FIELDS = (
    TENANT_ID_FIELD,
    KNOWLEDGE_BASE_ID_FIELD,
    OWNER_USER_ID_FIELD,
    DOCUMENT_ID_FIELD,
    CREATED_AT_FIELD,
)

OUTPUT_FIELDS = (
    CHUNK_ID_FIELD,
    DOCUMENT_ID_FIELD,
    KNOWLEDGE_BASE_ID_FIELD,
    OWNER_USER_ID_FIELD,
    TENANT_ID_FIELD,
    CONTENT_FIELD,
    SOURCE_FIELD,
    CREATED_AT_FIELD,
    METADATA_FIELD,
)


@dataclass(frozen=True, slots=True)
class MilvusFieldDefinition:
    """Serializable field description independent of a live Milvus client."""

    name: str
    data_type: str
    is_primary: bool = False
    max_length: int | None = None
    dimension: int | None = None


@dataclass(frozen=True, slots=True)
class MilvusCollectionSchemaDefinition:
    """Serializable collection schema description."""

    fields: tuple[MilvusFieldDefinition, ...]
    auto_id: bool = False
    enable_dynamic_field: bool = False


@dataclass(frozen=True, slots=True)
class MilvusIndexDefinition:
    """Serializable Milvus index definition."""

    field_name: str
    index_type: str
    metric_type: str | None = None
    params: dict[str, int | float | str] | None = None


def build_chunk_collection_schema(
    settings: MilvusVectorStoreSettings,
) -> MilvusCollectionSchemaDefinition:
    """Build the collection schema used for all knowledge base chunk vectors."""
    return MilvusCollectionSchemaDefinition(
        fields=(
            MilvusFieldDefinition(CHUNK_ID_FIELD, "VARCHAR", is_primary=True, max_length=128),
            MilvusFieldDefinition(DOCUMENT_ID_FIELD, "VARCHAR", max_length=128),
            MilvusFieldDefinition(KNOWLEDGE_BASE_ID_FIELD, "VARCHAR", max_length=128),
            MilvusFieldDefinition(OWNER_USER_ID_FIELD, "VARCHAR", max_length=128),
            MilvusFieldDefinition(TENANT_ID_FIELD, "VARCHAR", max_length=128),
            MilvusFieldDefinition(CONTENT_FIELD, "VARCHAR", max_length=65535),
            MilvusFieldDefinition(SOURCE_FIELD, "VARCHAR", max_length=1024),
            MilvusFieldDefinition(CREATED_AT_FIELD, "INT64"),
            MilvusFieldDefinition(METADATA_FIELD, "JSON"),
            MilvusFieldDefinition(
                VECTOR_FIELD,
                "FLOAT_VECTOR",
                dimension=settings.vector_dimension,
            ),
        )
    )


def build_index_definitions(
    settings: MilvusVectorStoreSettings,
) -> tuple[MilvusIndexDefinition, ...]:
    """Build scalar and vector indexes required for scoped retrieval."""
    scalar_indexes = tuple(
        MilvusIndexDefinition(field_name=field_name, index_type="AUTOINDEX")
        for field_name in SCALAR_FILTER_FIELDS
    )
    vector_index = MilvusIndexDefinition(
        field_name=VECTOR_FIELD,
        index_type=settings.index_type,
        metric_type=settings.metric_type,
        params=dict(settings.index_params),
    )
    return (*scalar_indexes, vector_index)
