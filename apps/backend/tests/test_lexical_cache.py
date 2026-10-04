from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import cast

import pytest

from super_ai.memory.repositories import KnowledgeDocumentRepository
from super_ai.retrieval.cache import LexicalCacheKey, LexicalIndexCache
from super_ai.retrieval.hybrid import Bm25Index, rank_bm25_documents
from super_ai.retrieval.tool import KnowledgeRetrievalTool, KnowledgeRetrievalToolInput
from super_ai.vector_store import StoredVectorChunk
from test_knowledge_retrieval_tool import (
    FakeEmbeddingModel,
    FakeRerankModel,
    FakeRetrievalVectorStore,
)


def _chunk(owner: str, text: str = "API timeout connection pool") -> StoredVectorChunk:
    return StoredVectorChunk(
        chunk_id=f"chunk-{owner}",
        document_id=f"doc-{owner}",
        knowledge_base_id=f"kb-{owner}",
        owner_user_id=owner,
        tenant_id=owner,
        content=text,
        source="runbook.md",
        created_at=1,
        metadata={},
    )


def _key(owner: str, revision: str = "v1") -> LexicalCacheKey:
    return LexicalCacheKey(owner, (f"kb-{owner}",), (), "{}", revision)


def test_cached_bm25_preserves_baseline_scores_and_empty_documents() -> None:
    documents = ["API timeout E_CONN_RESET", "API pool timeout", "正常运行", ""]
    index = Bm25Index(documents)
    for query in ["API timeout", "E_CONN_RESET", "正常", "unknown", ""]:
        assert index.rank(query=query) == rank_bm25_documents(query=query, documents=documents)
    assert Bm25Index(["", " "]).rank(query="API") == []


@pytest.mark.asyncio
async def test_concurrent_cache_miss_builds_once_and_separates_tenants() -> None:
    cache = LexicalIndexCache()
    load_count = 0

    async def load() -> list[StoredVectorChunk]:
        nonlocal load_count
        load_count += 1
        await asyncio.sleep(0.01)
        return [_chunk("a")]

    corpora = await asyncio.gather(*(cache.get_or_load(_key("a"), load) for _ in range(8)))
    assert load_count == 1
    assert all(corpus is corpora[0] for corpus in corpora)
    await cache.get_or_load(_key("b"), load)
    assert load_count == 2
    await cache.get_or_load(_key("a", "v2"), load)
    assert load_count == 3


@pytest.mark.asyncio
async def test_cache_evicts_by_capacity_and_does_not_retain_oversized_corpus() -> None:
    cache = LexicalIndexCache(max_entries=1, max_characters=50)
    load_count = 0

    async def load() -> list[StoredVectorChunk]:
        nonlocal load_count
        load_count += 1
        return [_chunk("a")]

    await cache.get_or_load(_key("a"), load)
    await cache.get_or_load(_key("b"), load)
    await cache.get_or_load(_key("a"), load)
    assert load_count == 3
    oversized = LexicalIndexCache(max_characters=1)
    await oversized.get_or_load(_key("a"), load)
    await oversized.get_or_load(_key("a"), load)
    assert load_count == 5


@pytest.mark.asyncio
async def test_cache_expiration_forces_reload() -> None:
    cache = LexicalIndexCache(ttl_seconds=0.001)
    load_count = 0

    async def load() -> list[StoredVectorChunk]:
        nonlocal load_count
        load_count += 1
        return [_chunk("a")]

    await cache.get_or_load(_key("a"), load)
    await asyncio.sleep(0.005)
    await cache.get_or_load(_key("a"), load)
    assert load_count == 2


@pytest.mark.asyncio
async def test_retrieval_cache_refreshes_when_document_version_changes() -> None:
    class VersionProvider:
        revision = "v1"

        async def lexical_revision(
            self, *, owner_user_id: str, knowledge_base_ids: Sequence[str]
        ) -> str:
            del owner_user_id, knowledge_base_ids
            return self.revision

    version = VersionProvider()
    vectors = FakeRetrievalVectorStore(chunks=[_chunk("a")])
    tool = KnowledgeRetrievalTool(
        embedding_model=FakeEmbeddingModel(),
        vector_store=vectors,
        rerank_model=FakeRerankModel(),
        lexical_cache=LexicalIndexCache(),
        document_repository=cast(KnowledgeDocumentRepository, version),
    )

    async def query() -> list[str]:
        result = await tool.run(
            KnowledgeRetrievalToolInput(query="API timeout"),
            owner_user_id="a",
            accessible_knowledge_base_ids=["kb-a"],
        )
        return [hit.chunk_id for hit in result.results]

    assert await query() == ["chunk-a"]
    assert await query() == ["chunk-a"]
    assert len(vectors.list_calls) == 1
    vectors.chunks = []
    version.revision = "v2"
    assert await query() == []
    assert len(vectors.list_calls) == 2


@pytest.mark.asyncio
async def test_warm_cache_never_shares_another_owners_chunks() -> None:
    class VersionProvider:
        async def lexical_revision(
            self, *, owner_user_id: str, knowledge_base_ids: Sequence[str]
        ) -> str:
            del owner_user_id, knowledge_base_ids
            return "same-version"

    vectors = FakeRetrievalVectorStore(chunks=[_chunk("a"), _chunk("b")])
    tool = KnowledgeRetrievalTool(
        embedding_model=FakeEmbeddingModel(),
        vector_store=vectors,
        rerank_model=FakeRerankModel(),
        lexical_cache=LexicalIndexCache(),
        document_repository=cast(KnowledgeDocumentRepository, VersionProvider()),
    )
    for owner in ["a", "b", "a"]:
        result = await tool.run(
            KnowledgeRetrievalToolInput(query="API timeout"),
            owner_user_id=owner,
            accessible_knowledge_base_ids=["kb-a", "kb-b"],
        )
        assert [hit.chunk_id for hit in result.results] == [f"chunk-{owner}"]
    assert len(vectors.list_calls) == 2
