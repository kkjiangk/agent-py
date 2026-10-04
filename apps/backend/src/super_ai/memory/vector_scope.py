"""Tenant ownership helpers for vector chunk metadata and Milvus filters."""

from __future__ import annotations

from collections.abc import Sequence


def build_vector_chunk_metadata(
    *,
    owner_user_id: str,
    tenant_id: str,
    knowledge_base_id: str,
    document_id: str,
    chunk_id: str,
) -> dict[str, str]:
    """Build metadata every vector chunk must carry before indexing."""
    return {
        "ownerUserId": owner_user_id,
        "tenantId": tenant_id,
        "knowledgeBaseId": knowledge_base_id,
        "documentId": document_id,
        "chunkId": chunk_id,
    }


def build_milvus_tenant_filter(*, tenant_id: str, knowledge_base_ids: Sequence[str]) -> str:
    """Build a Milvus boolean expression that scopes retrieval to accessible KBs."""
    quoted_kb_ids = ",".join(f'"{_escape_milvus_string(item)}"' for item in knowledge_base_ids)
    escaped_tenant_id = _escape_milvus_string(tenant_id)
    return f'tenantId == "{escaped_tenant_id}" && knowledgeBaseId in [{quoted_kb_ids}]'


def _escape_milvus_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
