"""Configuration for the Milvus-backed vector store."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from super_ai.project_config import (
    ProjectConfigurationError,
    project_config_section,
    required_dict,
    required_float,
    required_int,
    required_str,
)

DEFAULT_MILVUS_URI = "http://localhost:19530"
DEFAULT_COLLECTION_NAME = "knowledge_chunks"
DEFAULT_VECTOR_DIMENSION = 1024
DEFAULT_INDEX_TYPE = "HNSW"
DEFAULT_METRIC_TYPE = "COSINE"
DEFAULT_TIMEOUT_SECONDS = 10.0


class MilvusVectorStoreConfigurationError(RuntimeError):
    """Raised when Milvus vector store settings are invalid."""


def _default_index_params() -> dict[str, int | float | str]:
    return {"M": 16, "efConstruction": 200}


def _default_search_params() -> dict[str, int | float | str]:
    return {"ef": 64}


@dataclass(frozen=True, slots=True)
class MilvusVectorStoreSettings:
    """Typed settings for the Milvus vector store boundary."""

    uri: str = DEFAULT_MILVUS_URI
    collection_name: str = DEFAULT_COLLECTION_NAME
    vector_dimension: int = DEFAULT_VECTOR_DIMENSION
    index_type: str = DEFAULT_INDEX_TYPE
    metric_type: str = DEFAULT_METRIC_TYPE
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    index_params: dict[str, int | float | str] = field(default_factory=_default_index_params)
    search_params: dict[str, int | float | str] = field(default_factory=_default_search_params)


def load_milvus_vector_store_settings(
    config_path: Path | str | None = None,
) -> MilvusVectorStoreSettings:
    """Load Milvus settings from the repository project config."""
    try:
        config = project_config_section("vectorStore", config_path=config_path)
        settings = MilvusVectorStoreSettings(
            uri=required_str(config, "uri"),
            collection_name=required_str(config, "collectionName"),
            vector_dimension=required_int(config, "vectorDimension"),
            index_type=required_str(config, "indexType"),
            metric_type=required_str(config, "metricType"),
            timeout_seconds=required_float(config, "timeoutSeconds"),
            index_params=required_dict(config, "indexParams"),
            search_params=required_dict(config, "searchParams"),
        )
    except ProjectConfigurationError as exc:
        raise MilvusVectorStoreConfigurationError(str(exc)) from exc
    _validate_positive(settings.vector_dimension, "vectorDimension")
    _validate_positive(settings.timeout_seconds, "timeoutSeconds")
    return settings


def _validate_positive(value: int | float, key: str) -> None:
    if value <= 0:
        raise MilvusVectorStoreConfigurationError(f"Milvus setting must be positive: {key}")
