"""Milvus vector store boundary for knowledge base chunk embeddings."""

from super_ai.vector_store.config import (
    MilvusVectorStoreConfigurationError,
    MilvusVectorStoreSettings,
    load_milvus_vector_store_settings,
)
from super_ai.vector_store.milvus import (
    MilvusConnectionManager,
    MilvusHealthCheckResult,
    MilvusVectorStore,
    StoredVectorChunk,
    VectorChunkRecord,
    VectorSearchResult,
    build_default_milvus_vector_store,
)
from super_ai.vector_store.schema import (
    MilvusCollectionSchemaDefinition,
    MilvusFieldDefinition,
    MilvusIndexDefinition,
    build_chunk_collection_schema,
    build_index_definitions,
)

__all__ = [
    "MilvusCollectionSchemaDefinition",
    "MilvusConnectionManager",
    "MilvusFieldDefinition",
    "MilvusHealthCheckResult",
    "MilvusIndexDefinition",
    "MilvusVectorStore",
    "MilvusVectorStoreConfigurationError",
    "MilvusVectorStoreSettings",
    "StoredVectorChunk",
    "VectorChunkRecord",
    "VectorSearchResult",
    "build_chunk_collection_schema",
    "build_default_milvus_vector_store",
    "build_index_definitions",
    "load_milvus_vector_store_settings",
]
