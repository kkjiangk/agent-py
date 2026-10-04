from __future__ import annotations

import threading
from collections.abc import Sequence

import pytest

from super_ai.llm import RerankResult
from super_ai.retrieval import (
    KNOWLEDGE_RETRIEVAL_TOOL_NAME,
    KnowledgeRetrievalError,
    KnowledgeRetrievalFilters,
    KnowledgeRetrievalTool,
    KnowledgeRetrievalToolInput,
    create_langchain_knowledge_retrieval_tool,
)
from super_ai.vector_store import StoredVectorChunk, VectorSearchResult


class FakeEmbeddingModel:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.inputs: list[list[str]] = []

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        self.inputs.append(texts)
        if self.error is not None:
            raise self.error
        return [[0.1, 0.2, 0.3] for _text in texts]


class FakeRetrievalVectorStore:
    def __init__(
        self,
        *,
        results: Sequence[VectorSearchResult] = (),
        chunks: Sequence[StoredVectorChunk] | None = None,
        error: Exception | None = None,
        list_error: Exception | None = None,
    ) -> None:
        self.results = list(results)
        self.chunks = list(chunks) if chunks is not None else [
            StoredVectorChunk(
                chunk_id=result.chunk_id,
                document_id=result.document_id,
                knowledge_base_id=result.knowledge_base_id,
                owner_user_id=result.owner_user_id,
                tenant_id=result.tenant_id,
                content=result.content,
                source=result.source,
                created_at=result.created_at,
                metadata=result.metadata,
            )
            for result in results
        ]
        self.error = error
        self.list_error = list_error
        self.searches: list[dict[str, object]] = []
        self.list_calls: list[dict[str, object]] = []

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
        if self.error is not None:
            raise self.error
        return self.results

    def list_chunks(
        self,
        *,
        tenant_id: str,
        knowledge_base_ids: Sequence[str],
    ) -> list[StoredVectorChunk]:
        self.list_calls.append(
            {
                "tenant_id": tenant_id,
                "knowledge_base_ids": list(knowledge_base_ids),
            }
        )
        if self.list_error is not None:
            raise self.list_error
        return self.chunks


class FakeRerankModel:
    def __init__(self, scores: Sequence[float] = (), error: Exception | None = None) -> None:
        self.scores = list(scores)
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def arerank(
        self, *, query: str, documents: Sequence[str], top_n: int
    ) -> list[RerankResult]:
        self.calls.append({"query": query, "documents": list(documents), "top_n": top_n})
        if self.error is not None:
            raise self.error
        scores = self.scores or [1 - index / 100 for index in range(len(documents))]
        ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
        return [
            RerankResult(index=index, relevance_score=score)
            for index, score in ranked[:top_n]
        ]


@pytest.mark.asyncio
async def test_retrieval_tool_returns_hits_and_citations_with_scoped_search() -> None:
    hit = VectorSearchResult(
        chunk_id="chunk_1",
        document_id="doc_1",
        knowledge_base_id="kb_user_a",
        owner_user_id="user_a",
        tenant_id="user_a",
        content="Restart the API deployment from the runbook.",
        source="runbook.md",
        created_at=1_775_779_200_000,
        metadata={"section": "restart", "knowledgeType": "sop"},
        score=0.87,
    )
    embedding_model = FakeEmbeddingModel()
    vector_store = FakeRetrievalVectorStore(results=[hit])
    rerank_model = FakeRerankModel(scores=[0.96])
    tool = KnowledgeRetrievalTool(
        embedding_model=embedding_model,
        vector_store=vector_store,
        rerank_model=rerank_model,
    )

    result = await tool.run(
        KnowledgeRetrievalToolInput(
            query="how do I restart the API?",
            top_k=3,
            filters=KnowledgeRetrievalFilters(knowledge_base_ids=("kb_user_a",)),
        ),
        owner_user_id="user_a",
        accessible_knowledge_base_ids=("kb_user_a", "kb_user_a_secondary"),
    )

    assert KNOWLEDGE_RETRIEVAL_TOOL_NAME == "knowledge_retrieval"
    assert embedding_model.inputs == [["how do I restart the API?"]]
    assert vector_store.searches == [
        {
            "query_vector": [0.1, 0.2, 0.3],
            "tenant_id": "user_a",
            "knowledge_base_ids": ["kb_user_a"],
            "limit": 20,
        }
    ]
    assert result.query == "how do I restart the API?"
    assert [item.content for item in result.results] == [hit.content]
    assert result.results[0].metadata["section"] == "restart"
    assert result.citations[0].chunk_id == "chunk_1"
    assert result.citations[0].source_type == "knowledge-base"
    assert result.citations[0].score == 0.96
    assert result.citations[0].vector_rank == 1
    assert result.citations[0].bm25_rank == 1
    assert result.citations[0].rerank_rank == 1
    assert result.citations[0].rerank_score == 0.96
    assert result.citations[0].vector_score == 0.87
    assert result.citations[0].bm25_score is not None
    assert result.citations[0].rrf_score == pytest.approx(2 / 61)
    assert result.citations[0].knowledge_type == "sop"
    assert result.citations[0].excerpt == "Restart the API deployment from the runbook."


@pytest.mark.asyncio
async def test_retrieval_tool_returns_empty_results_without_fabricating_content() -> None:
    tool = KnowledgeRetrievalTool(
        embedding_model=FakeEmbeddingModel(),
        vector_store=FakeRetrievalVectorStore(results=[]),
        rerank_model=FakeRerankModel(),
    )

    result = await tool.run(
        KnowledgeRetrievalToolInput(query="nothing matches"),
        owner_user_id="user_a",
        accessible_knowledge_base_ids=("kb_user_a",),
    )

    assert result.results == []
    assert result.citations == []
    assert result.top_k == 5


@pytest.mark.asyncio
async def test_retrieval_tool_filters_hits_by_document_metadata_and_scope() -> None:
    matching_hit = VectorSearchResult(
        chunk_id="chunk_match",
        document_id="doc_match",
        knowledge_base_id="kb_user_a",
        owner_user_id="user_a",
        tenant_id="user_a",
        content="Restart the API deployment.",
        source="runbook.md",
        created_at=1_775_779_200_000,
        metadata={"section": "restart", "environment": "prod"},
        score=0.9,
    )
    wrong_document = VectorSearchResult(
        chunk_id="chunk_wrong_document",
        document_id="doc_other",
        knowledge_base_id="kb_user_a",
        owner_user_id="user_a",
        tenant_id="user_a",
        content="Different document.",
        source="other.md",
        created_at=1_775_779_200_000,
        metadata={"section": "restart", "environment": "prod"},
        score=0.91,
    )
    wrong_tenant = VectorSearchResult(
        chunk_id="chunk_wrong_tenant",
        document_id="doc_match",
        knowledge_base_id="kb_user_a",
        owner_user_id="user_b",
        tenant_id="user_b",
        content="Another tenant.",
        source="leak.md",
        created_at=1_775_779_200_000,
        metadata={"section": "restart", "environment": "prod"},
        score=0.99,
    )
    wrong_metadata = VectorSearchResult(
        chunk_id="chunk_wrong_metadata",
        document_id="doc_match",
        knowledge_base_id="kb_user_a",
        owner_user_id="user_a",
        tenant_id="user_a",
        content="Wrong section.",
        source="runbook.md",
        created_at=1_775_779_200_000,
        metadata={"section": "deploy", "environment": "prod"},
        score=0.88,
    )
    tool = KnowledgeRetrievalTool(
        embedding_model=FakeEmbeddingModel(),
        vector_store=FakeRetrievalVectorStore(
            results=[wrong_tenant, wrong_document, wrong_metadata, matching_hit]
        ),
        rerank_model=FakeRerankModel(),
    )

    result = await tool.run(
        KnowledgeRetrievalToolInput(
            query="restart",
            filters=KnowledgeRetrievalFilters(
                knowledge_base_ids=("kb_user_a",),
                document_ids=("doc_match",),
                metadata={"section": "restart"},
            ),
        ),
        owner_user_id="user_a",
        accessible_knowledge_base_ids=("kb_user_a",),
    )

    assert [item.chunk_id for item in result.results] == ["chunk_match"]
    assert [item.chunk_id for item in result.citations] == ["chunk_match"]


@pytest.mark.asyncio
async def test_retrieval_tool_returns_at_most_five_hits_in_rerank_order() -> None:
    hits = [
        VectorSearchResult(
            chunk_id=f"chunk_{index}",
            document_id=f"doc_{index}",
            knowledge_base_id="kb_user_a",
            owner_user_id="user_a",
            tenant_id="user_a",
            content=f"content {index}",
            source=f"source-{index}.md",
            created_at=1_775_779_200_000,
            metadata={},
            score=0.99 - index / 100,
        )
        for index in range(8)
    ]
    tool = KnowledgeRetrievalTool(
        embedding_model=FakeEmbeddingModel(),
        vector_store=FakeRetrievalVectorStore(results=hits),
        rerank_model=FakeRerankModel(
            scores=[0.1, 0.8, 0.3, 0.99, 0.5, 0.9, 0.2, 0.7]
        ),
    )

    result = await tool.run(
        KnowledgeRetrievalToolInput(query="rank", top_k=20),
        owner_user_id="user_a",
        accessible_knowledge_base_ids=("kb_user_a",),
    )

    assert result.top_k == 5
    assert [hit.chunk_id for hit in result.results] == [
        "chunk_3",
        "chunk_5",
        "chunk_1",
        "chunk_7",
        "chunk_4",
    ]
    assert [hit.score for hit in result.results] == sorted(
        [hit.score for hit in result.results], reverse=True
    )
    assert [hit.rerank_rank for hit in result.results] == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_retrieval_tool_does_not_fall_back_when_rerank_fails() -> None:
    hit = VectorSearchResult(
        chunk_id="chunk_1",
        document_id="doc_1",
        knowledge_base_id="kb_user_a",
        owner_user_id="user_a",
        tenant_id="user_a",
        content="restart",
        source="runbook.md",
        created_at=1_775_779_200_000,
        metadata={},
        score=0.99,
    )
    tool = KnowledgeRetrievalTool(
        embedding_model=FakeEmbeddingModel(),
        vector_store=FakeRetrievalVectorStore(results=[hit]),
        rerank_model=FakeRerankModel(error=RuntimeError("upstream unavailable")),
    )

    with pytest.raises(KnowledgeRetrievalError) as exc_info:
        await tool.run(
            KnowledgeRetrievalToolInput(query="restart"),
            owner_user_id="user_a",
            accessible_knowledge_base_ids=("kb_user_a",),
        )

    assert exc_info.value.code == "SYSTEM_UNAVAILABLE"
    assert "reranking" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_retrieval_tool_rejects_empty_query_before_embedding_or_search() -> None:
    embedding_model = FakeEmbeddingModel()
    vector_store = FakeRetrievalVectorStore()
    tool = KnowledgeRetrievalTool(
        embedding_model=embedding_model,
        vector_store=vector_store,
        rerank_model=FakeRerankModel(),
    )

    with pytest.raises(KnowledgeRetrievalError) as exc_info:
        await tool.run(
            KnowledgeRetrievalToolInput(query="   "),
            owner_user_id="user_a",
            accessible_knowledge_base_ids=("kb_user_a",),
        )

    assert exc_info.value.code == "VALIDATION_INVALID_ARGUMENT"
    assert embedding_model.inputs == []
    assert vector_store.searches == []
    assert vector_store.list_calls == []


@pytest.mark.asyncio
async def test_retrieval_tool_rejects_unauthorized_knowledge_base_filter() -> None:
    embedding_model = FakeEmbeddingModel()
    vector_store = FakeRetrievalVectorStore()
    tool = KnowledgeRetrievalTool(
        embedding_model=embedding_model,
        vector_store=vector_store,
        rerank_model=FakeRerankModel(),
    )

    with pytest.raises(KnowledgeRetrievalError) as exc_info:
        await tool.run(
            KnowledgeRetrievalToolInput(
                query="restart",
                filters=KnowledgeRetrievalFilters(knowledge_base_ids=("kb_other",)),
            ),
            owner_user_id="user_a",
            accessible_knowledge_base_ids=("kb_user_a",),
        )

    assert exc_info.value.code == "AUTH_FORBIDDEN"
    assert embedding_model.inputs == []
    assert vector_store.searches == []
    assert vector_store.list_calls == []


@pytest.mark.asyncio
async def test_retrieval_tool_returns_safe_error_for_embedding_or_vector_failures() -> None:
    tool = KnowledgeRetrievalTool(
        embedding_model=FakeEmbeddingModel(error=RuntimeError("provider leaked sk-secret")),
        vector_store=FakeRetrievalVectorStore(),
        rerank_model=FakeRerankModel(),
    )

    with pytest.raises(KnowledgeRetrievalError) as exc_info:
        await tool.run(
            KnowledgeRetrievalToolInput(query="restart"),
            owner_user_id="user_a",
            accessible_knowledge_base_ids=("kb_user_a",),
        )

    assert exc_info.value.code == "SYSTEM_UNAVAILABLE"
    assert "sk-secret" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_retrieval_tool_returns_safe_error_for_chunk_enumeration_failure() -> None:
    tool = KnowledgeRetrievalTool(
        embedding_model=FakeEmbeddingModel(),
        vector_store=FakeRetrievalVectorStore(
            list_error=RuntimeError("milvus transport secret")
        ),
        rerank_model=FakeRerankModel(),
    )

    with pytest.raises(KnowledgeRetrievalError) as exc_info:
        await tool.run(
            KnowledgeRetrievalToolInput(query="restart"),
            owner_user_id="user_a",
            accessible_knowledge_base_ids=("kb_user_a",),
        )

    assert exc_info.value.code == "SYSTEM_UNAVAILABLE"
    assert "transport secret" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_retrieval_tool_returns_safe_error_for_bm25_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_bm25(**_kwargs: object) -> object:
        raise RuntimeError("bm25 internal details")

    monkeypatch.setattr("super_ai.retrieval.tool.rank_bm25_documents", fail_bm25)
    tool = KnowledgeRetrievalTool(
        embedding_model=FakeEmbeddingModel(),
        vector_store=FakeRetrievalVectorStore(),
        rerank_model=FakeRerankModel(),
    )

    with pytest.raises(KnowledgeRetrievalError) as exc_info:
        await tool.run(
            KnowledgeRetrievalToolInput(query="restart"),
            owner_user_id="user_a",
            accessible_knowledge_base_ids=("kb_user_a",),
        )

    assert exc_info.value.code == "SYSTEM_UNAVAILABLE"
    assert "internal details" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_retrieval_tool_can_be_bound_as_langchain_tool_with_tenant_scope() -> None:
    hit = VectorSearchResult(
        chunk_id="chunk_1",
        document_id="doc_1",
        knowledge_base_id="kb_user_a",
        owner_user_id="user_a",
        tenant_id="user_a",
        content="Restart the API deployment from the runbook.",
        source="runbook.md",
        created_at=1_775_779_200_000,
        metadata={"section": "restart"},
        score=0.87,
    )
    vector_store = FakeRetrievalVectorStore(results=[hit])
    tool = KnowledgeRetrievalTool(
        embedding_model=FakeEmbeddingModel(),
        vector_store=vector_store,
        rerank_model=FakeRerankModel(),
    )
    langchain_tool = create_langchain_knowledge_retrieval_tool(
        tool,
        owner_user_id="user_a",
        accessible_knowledge_base_ids=("kb_user_a",),
    )

    result = await langchain_tool.ainvoke(
        {
            "query": "restart api",
            "topK": 2,
            "filters": {"knowledgeBaseIds": ["kb_user_a"]},
        }
    )

    assert langchain_tool.name == KNOWLEDGE_RETRIEVAL_TOOL_NAME
    assert result["results"][0]["chunkId"] == "chunk_1"
    assert result["results"][0]["bm25Score"] is not None
    assert result["results"][0]["vectorRank"] == 1
    assert result["results"][0]["bm25Rank"] == 1
    assert result["results"][0]["rerankRank"] == 1
    assert result["results"][0]["rrfScore"] == pytest.approx(2 / 61)
    assert result["citations"][0]["documentId"] == "doc_1"
    assert vector_store.searches[0]["tenant_id"] == "user_a"


@pytest.mark.asyncio
async def test_langchain_retrieval_tool_accepts_json_encoded_filters_from_model() -> None:
    tool = KnowledgeRetrievalTool(
        embedding_model=FakeEmbeddingModel(),
        vector_store=FakeRetrievalVectorStore(),
        rerank_model=FakeRerankModel(),
    )
    langchain_tool = create_langchain_knowledge_retrieval_tool(
        tool,
        owner_user_id="user_a",
        accessible_knowledge_base_ids=("kb_user_a",),
    )

    result = await langchain_tool.ainvoke(
        {"query": "restart", "filters": '{"documentIds":["doc_1"]}'},
    )

    assert result["results"] == []


@pytest.mark.asyncio
async def test_keyword_only_candidate_enters_rrf_and_rerank() -> None:
    vector_hit = VectorSearchResult(
        chunk_id="semantic",
        document_id="doc_semantic",
        knowledge_base_id="kb_user_a",
        owner_user_id="user_a",
        tenant_id="user_a",
        content="General service troubleshooting guidance.",
        source="general.md",
        created_at=1,
        metadata={},
        score=0.91,
    )
    exact_chunk = StoredVectorChunk(
        chunk_id="exact",
        document_id="doc_exact",
        knowledge_base_id="kb_user_a",
        owner_user_id="user_a",
        tenant_id="user_a",
        content="错误码 InternalError.Algo.InvalidParameter 的批次不能超过 10。",
        source="embedding-errors.md",
        created_at=2,
        metadata={"section": "embedding"},
    )
    rerank = FakeRerankModel(scores=[0.99, 0.2])
    tool = KnowledgeRetrievalTool(
        embedding_model=FakeEmbeddingModel(),
        vector_store=FakeRetrievalVectorStore(
            results=[vector_hit],
            chunks=[exact_chunk],
        ),
        rerank_model=rerank,
    )

    result = await tool.run(
        KnowledgeRetrievalToolInput(query="InternalError.Algo.InvalidParameter"),
        owner_user_id="user_a",
        accessible_knowledge_base_ids=("kb_user_a",),
    )

    assert rerank.calls[0]["documents"] == [exact_chunk.content, vector_hit.content]
    assert result.results[0].chunk_id == "exact"
    assert result.results[0].vector_rank is None
    assert result.results[0].bm25_rank == 1
    assert result.results[0].rerank_rank == 1
    assert result.results[0].vector_score is None
    assert result.results[0].bm25_score is not None
    assert result.results[0].rrf_score == pytest.approx(1 / 61)


@pytest.mark.asyncio
async def test_vector_and_bm25_recall_execute_concurrently() -> None:
    barrier = threading.Barrier(2, timeout=2)

    class ConcurrentStore(FakeRetrievalVectorStore):
        def search_chunks(
            self,
            *,
            query_vector: Sequence[float],
            tenant_id: str,
            knowledge_base_ids: Sequence[str],
            limit: int,
        ) -> list[VectorSearchResult]:
            barrier.wait()
            return super().search_chunks(
                query_vector=query_vector,
                tenant_id=tenant_id,
                knowledge_base_ids=knowledge_base_ids,
                limit=limit,
            )

        def list_chunks(
            self,
            *,
            tenant_id: str,
            knowledge_base_ids: Sequence[str],
        ) -> list[StoredVectorChunk]:
            barrier.wait()
            return super().list_chunks(
                tenant_id=tenant_id,
                knowledge_base_ids=knowledge_base_ids,
            )

    tool = KnowledgeRetrievalTool(
        embedding_model=FakeEmbeddingModel(),
        vector_store=ConcurrentStore(),
        rerank_model=FakeRerankModel(),
    )

    result = await tool.run(
        KnowledgeRetrievalToolInput(query="parallel"),
        owner_user_id="user_a",
        accessible_knowledge_base_ids=("kb_user_a",),
    )

    assert result.results == []
