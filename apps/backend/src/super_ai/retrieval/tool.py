"""Agent-facing knowledge retrieval tool."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, field_validator

from super_ai.llm import EmbeddingModel, RerankModel
from super_ai.memory.repositories import KnowledgeDocumentRepository
from super_ai.vector_store import StoredVectorChunk, VectorSearchResult

from .cache import LexicalCacheKey, LexicalIndexCache
from .hybrid import (
    BM25_CANDIDATE_LIMIT,
    RRF_K,
    Bm25Rank,
    rank_bm25_documents,
    reciprocal_rank_fusion,
)

KNOWLEDGE_RETRIEVAL_TOOL_NAME = "knowledge_retrieval"
DEFAULT_RETRIEVAL_TOP_K = 5
MAX_RETRIEVAL_TOP_K = 5
RERANK_CANDIDATE_LIMIT = 20
MAX_CITATION_EXCERPT_LENGTH = 480


class RetrievalVectorStore(Protocol):
    """Vector search boundary required by the retrieval tool."""

    def search_chunks(
        self,
        *,
        query_vector: Sequence[float],
        tenant_id: str,
        knowledge_base_ids: Sequence[str],
        limit: int,
    ) -> list[VectorSearchResult]:
        """Search tenant-scoped knowledge chunks."""
        ...

    def list_chunks(
        self,
        *,
        tenant_id: str,
        knowledge_base_ids: Sequence[str],
    ) -> list[StoredVectorChunk]:
        """List tenant-scoped scalar chunk data for lexical retrieval."""
        ...


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalFilters:
    """Optional retrieval filters requested by the model/tool caller."""

    knowledge_base_ids: Sequence[str] = field(default_factory=tuple)
    document_ids: Sequence[str] = field(default_factory=tuple)
    metadata: Mapping[str, str | int | float | bool] = field(default_factory=lambda: {})


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalToolInput:
    """Typed input accepted by the knowledge retrieval tool."""

    query: str
    top_k: int | None = None
    filters: KnowledgeRetrievalFilters | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalHit:
    """Structured retrieval hit returned to agent orchestration."""

    chunk_id: str
    document_id: str
    knowledge_base_id: str
    owner_user_id: str
    tenant_id: str
    content: str
    source: str
    metadata: Mapping[str, object]
    score: float
    vector_rank: int | None = None
    bm25_rank: int | None = None
    rerank_rank: int | None = None
    vector_score: float | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalCitationSource:
    """Reference-source payload derived from a retrieval hit."""

    id: str
    title: str
    source_type: str
    chunk_id: str
    document_id: str
    knowledge_base_id: str
    source: str
    metadata: Mapping[str, object]
    score: float
    excerpt: str
    knowledge_type: str
    uri: str | None = None
    vector_rank: int | None = None
    bm25_rank: int | None = None
    rerank_rank: int | None = None
    vector_score: float | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalToolResult:
    """Complete retrieval tool output."""

    query: str
    top_k: int
    results: list[KnowledgeRetrievalHit]
    citations: list[KnowledgeRetrievalCitationSource]


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalError(Exception):
    """Unified retrieval error that can be mapped to API error responses."""

    code: str
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class _FusedCandidate:
    chunk: StoredVectorChunk
    vector_rank: int | None
    bm25_rank: int | None
    vector_score: float | None
    bm25_score: float | None
    rrf_score: float


class _ScopedChunk(Protocol):
    @property
    def chunk_id(self) -> str: ...

    @property
    def document_id(self) -> str: ...

    @property
    def knowledge_base_id(self) -> str: ...

    @property
    def owner_user_id(self) -> str: ...

    @property
    def tenant_id(self) -> str: ...

    @property
    def metadata(self) -> Mapping[str, object]: ...


ScopedChunkT = TypeVar("ScopedChunkT", bound=_ScopedChunk)


class KnowledgeRetrievalTool:
    """Tenant-scoped knowledge base retrieval tool for agent use."""

    name = KNOWLEDGE_RETRIEVAL_TOOL_NAME
    description = "Search the current user's indexed knowledge base documents."

    def __init__(
        self,
        *,
        embedding_model: EmbeddingModel,
        vector_store: RetrievalVectorStore,
        rerank_model: RerankModel,
        lexical_cache: LexicalIndexCache | None = None,
        document_repository: KnowledgeDocumentRepository | None = None,
    ) -> None:
        self._embedding_model = embedding_model
        self._vector_store = vector_store
        self._rerank_model = rerank_model
        if lexical_cache is not None and document_repository is None:
            raise ValueError("A version provider is required for cached lexical retrieval.")
        self._lexical_cache = lexical_cache
        self._document_repository = document_repository

    async def run(
        self,
        input: KnowledgeRetrievalToolInput,
        *,
        owner_user_id: str,
        accessible_knowledge_base_ids: Sequence[str],
    ) -> KnowledgeRetrievalToolResult:
        query = input.query.strip()
        if not query:
            raise KnowledgeRetrievalError(
                code="VALIDATION_INVALID_ARGUMENT",
                message="Retrieval query is required.",
            )
        top_k = _bounded_top_k(input.top_k)
        filters = input.filters or KnowledgeRetrievalFilters()
        knowledge_base_ids = _resolve_knowledge_base_ids(
            requested_ids=(
                filters.knowledge_base_ids
            ),
            accessible_ids=accessible_knowledge_base_ids,
        )
        if not knowledge_base_ids:
            return KnowledgeRetrievalToolResult(query=query, top_k=top_k, results=[], citations=[])

        try:
            vector_hits, keyword_recall = await asyncio.gather(
                self._vector_recall(
                    query=query,
                    owner_user_id=owner_user_id,
                    knowledge_base_ids=knowledge_base_ids,
                ),
                self._keyword_recall(
                    query=query,
                    owner_user_id=owner_user_id,
                    knowledge_base_ids=knowledge_base_ids,
                    filters=filters,
                ),
            )
        except KnowledgeRetrievalError:
            raise
        except Exception as exc:
            raise KnowledgeRetrievalError(
                code="SYSTEM_UNAVAILABLE",
                message="Knowledge retrieval is temporarily unavailable.",
            ) from exc

        filtered_vector_hits = _filter_chunks(
            vector_hits,
            owner_user_id=owner_user_id,
            knowledge_base_ids=knowledge_base_ids,
            filters=filters,
        )
        filtered_keyword_chunks, bm25_ranks = keyword_recall
        candidates = _fuse_candidates(
            vector_hits=filtered_vector_hits[:RERANK_CANDIDATE_LIMIT],
            keyword_chunks=filtered_keyword_chunks,
            bm25_ranks=bm25_ranks,
        )
        if not candidates:
            return KnowledgeRetrievalToolResult(
                query=query, top_k=top_k, results=[], citations=[]
            )
        try:
            rankings = await self._rerank_model.arerank(
                query=query,
                documents=[candidate.chunk.content for candidate in candidates],
                top_n=min(top_k, len(candidates)),
            )
        except Exception as exc:
            raise KnowledgeRetrievalError(
                code="SYSTEM_UNAVAILABLE",
                message="Knowledge reranking is temporarily unavailable.",
            ) from exc
        results = [
            _hit_from_fused_candidate(
                candidates[ranking.index],
                rerank_rank=rerank_rank,
                rerank_score=ranking.relevance_score,
            )
            for rerank_rank, ranking in enumerate(rankings, start=1)
        ]
        citations = [_citation_from_hit(hit) for hit in results]
        return KnowledgeRetrievalToolResult(
            query=query,
            top_k=top_k,
            results=results,
            citations=citations,
        )

    async def _vector_recall(
        self,
        *,
        query: str,
        owner_user_id: str,
        knowledge_base_ids: Sequence[str],
    ) -> list[VectorSearchResult]:
        vectors = await self._embedding_model.aembed_documents([query])
        query_vector = _single_query_vector(vectors)
        return await asyncio.to_thread(
            self._vector_store.search_chunks,
            query_vector=query_vector,
            tenant_id=owner_user_id,
            knowledge_base_ids=knowledge_base_ids,
            limit=RERANK_CANDIDATE_LIMIT,
        )

    async def _keyword_recall(
        self,
        *,
        query: str,
        owner_user_id: str,
        knowledge_base_ids: Sequence[str],
        filters: KnowledgeRetrievalFilters,
    ) -> tuple[list[StoredVectorChunk], list[Bm25Rank]]:
        if self._lexical_cache is not None and self._document_repository is not None:
            for _ in range(2):
                revision = await self._document_repository.lexical_revision(
                    owner_user_id=owner_user_id, knowledge_base_ids=knowledge_base_ids
                )
                key = LexicalCacheKey(
                    owner_user_id=owner_user_id,
                    knowledge_base_ids=tuple(sorted(set(knowledge_base_ids))),
                    document_ids=tuple(sorted(set(filters.document_ids))),
                    metadata_json=json.dumps(dict(filters.metadata), sort_keys=True),
                    revision=revision,
                )

                async def load() -> list[StoredVectorChunk]:
                    return await self._load_keyword_chunks(
                        owner_user_id=owner_user_id, knowledge_base_ids=knowledge_base_ids,
                        filters=filters,
                    )

                corpus = await self._lexical_cache.get_or_load(key, load)
                current_revision = await self._document_repository.lexical_revision(
                    owner_user_id=owner_user_id, knowledge_base_ids=knowledge_base_ids
                )
                if revision == current_revision:
                    ranks = await asyncio.to_thread(
                        corpus.index.rank, query=query, limit=BM25_CANDIDATE_LIMIT
                    )
                    return list(corpus.chunks), ranks
                self._lexical_cache.discard(key)
            raise KnowledgeRetrievalError(
                code="SYSTEM_UNAVAILABLE",
                message="Knowledge index changed during retrieval. Please retry.",
            )
        filtered_chunks = await self._load_keyword_chunks(
            owner_user_id=owner_user_id, knowledge_base_ids=knowledge_base_ids, filters=filters
        )
        ranks = await asyncio.to_thread(
            rank_bm25_documents, query=query,
            documents=[chunk.content for chunk in filtered_chunks], limit=BM25_CANDIDATE_LIMIT,
        )
        return filtered_chunks, ranks

    async def _load_keyword_chunks(
        self, *, owner_user_id: str, knowledge_base_ids: Sequence[str],
        filters: KnowledgeRetrievalFilters,
    ) -> list[StoredVectorChunk]:
        chunks = await asyncio.to_thread(
            self._vector_store.list_chunks,
            tenant_id=owner_user_id,
            knowledge_base_ids=knowledge_base_ids,
        )
        filtered_chunks = _filter_chunks(
            chunks,
            owner_user_id=owner_user_id,
            knowledge_base_ids=knowledge_base_ids,
            filters=filters,
        )
        return filtered_chunks


class LangChainKnowledgeRetrievalFilters(BaseModel):
    """LangChain tool input filter schema."""

    model_config = ConfigDict(populate_by_name=True)

    knowledge_base_ids: list[str] = Field(default_factory=list, alias="knowledgeBaseIds")
    document_ids: list[str] = Field(default_factory=list, alias="documentIds")
    metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)


class LangChainKnowledgeRetrievalInput(BaseModel):
    """LangChain tool input schema."""

    model_config = ConfigDict(populate_by_name=True)

    query: str
    top_k: int | None = Field(default=None, alias="topK")
    filters: LangChainKnowledgeRetrievalFilters | None = None

    @field_validator("filters", mode="before")
    @classmethod
    def parse_serialized_filters(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        try:
            parsed: object = json.loads(value)
        except json.JSONDecodeError:
            return value
        return parsed


def create_langchain_knowledge_retrieval_tool(
    retrieval_tool: KnowledgeRetrievalTool,
    *,
    owner_user_id: str,
    accessible_knowledge_base_ids: Sequence[str],
) -> StructuredTool:
    """Create a request-scoped LangChain tool for tenant-safe knowledge retrieval."""

    async def run_knowledge_retrieval(
        query: str,
        top_k: int | None = None,
        filters: LangChainKnowledgeRetrievalFilters | None = None,
    ) -> dict[str, object]:
        result = await retrieval_tool.run(
            KnowledgeRetrievalToolInput(
                query=query,
                top_k=top_k,
                filters=_filters_from_langchain(filters),
            ),
            owner_user_id=owner_user_id,
            accessible_knowledge_base_ids=accessible_knowledge_base_ids,
        )
        return _result_payload(result)

    return StructuredTool.from_function(
        coroutine=run_knowledge_retrieval,
        name=KNOWLEDGE_RETRIEVAL_TOOL_NAME,
        description=KnowledgeRetrievalTool.description,
        args_schema=LangChainKnowledgeRetrievalInput,
    )


def _bounded_top_k(value: int | None) -> int:
    if value is None:
        return DEFAULT_RETRIEVAL_TOP_K
    if value < 1:
        raise KnowledgeRetrievalError(
            code="VALIDATION_INVALID_ARGUMENT",
            message="Retrieval topK must be greater than zero.",
        )
    return min(value, MAX_RETRIEVAL_TOP_K)


def _resolve_knowledge_base_ids(
    *,
    requested_ids: Sequence[str],
    accessible_ids: Sequence[str],
) -> list[str]:
    accessible = list(dict.fromkeys(accessible_ids))
    if not requested_ids:
        return accessible
    requested = list(dict.fromkeys(requested_ids))
    unauthorized = [item for item in requested if item not in accessible]
    if unauthorized:
        raise KnowledgeRetrievalError(
            code="AUTH_FORBIDDEN",
            message="You do not have permission to access this knowledge base.",
        )
    return requested


def _single_query_vector(vectors: Sequence[Sequence[float]]) -> Sequence[float]:
    if len(vectors) != 1:
        raise KnowledgeRetrievalError(
            code="SYSTEM_UNAVAILABLE",
            message="Knowledge retrieval is temporarily unavailable.",
        )
    return vectors[0]


def _filter_chunks(
    hits: Sequence[ScopedChunkT],
    *,
    owner_user_id: str,
    knowledge_base_ids: Sequence[str],
    filters: KnowledgeRetrievalFilters,
) -> list[ScopedChunkT]:
    allowed_knowledge_base_ids = set(knowledge_base_ids)
    requested_document_ids = set(filters.document_ids)
    return [
        hit
        for hit in hits
        if hit.owner_user_id == owner_user_id
        and hit.tenant_id == owner_user_id
        and hit.knowledge_base_id in allowed_knowledge_base_ids
        and (not requested_document_ids or hit.document_id in requested_document_ids)
        and _metadata_matches(hit.metadata, filters.metadata)
    ]


def _metadata_matches(
    hit_metadata: Mapping[str, object],
    required_metadata: Mapping[str, str | int | float | bool],
) -> bool:
    return all(hit_metadata.get(key) == value for key, value in required_metadata.items())


def _fuse_candidates(
    *,
    vector_hits: Sequence[VectorSearchResult],
    keyword_chunks: Sequence[StoredVectorChunk],
    bm25_ranks: Sequence[Bm25Rank],
) -> list[_FusedCandidate]:
    bm25_chunks = [keyword_chunks[rank.index] for rank in bm25_ranks]
    fused_ranks = reciprocal_rank_fusion(
        vector_keys=[hit.chunk_id for hit in vector_hits],
        bm25_keys=[chunk.chunk_id for chunk in bm25_chunks],
        limit=RERANK_CANDIDATE_LIMIT,
        k=RRF_K,
    )
    vector_by_id = {hit.chunk_id: hit for hit in vector_hits}
    keyword_by_id = {chunk.chunk_id: chunk for chunk in bm25_chunks}
    bm25_score_by_id = {
        chunk.chunk_id: rank.score
        for chunk, rank in zip(bm25_chunks, bm25_ranks, strict=True)
    }
    return [
        _FusedCandidate(
            chunk=(
                _stored_chunk_from_vector_result(vector_by_id[fused.key])
                if fused.key in vector_by_id
                else keyword_by_id[fused.key]
            ),
            vector_rank=fused.vector_rank,
            bm25_rank=fused.bm25_rank,
            vector_score=(
                vector_by_id[fused.key].score if fused.key in vector_by_id else None
            ),
            bm25_score=bm25_score_by_id.get(fused.key),
            rrf_score=fused.score,
        )
        for fused in fused_ranks
    ]


def _stored_chunk_from_vector_result(result: VectorSearchResult) -> StoredVectorChunk:
    return StoredVectorChunk(
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


def _hit_from_fused_candidate(
    candidate: _FusedCandidate, *, rerank_rank: int, rerank_score: float
) -> KnowledgeRetrievalHit:
    result = candidate.chunk
    return KnowledgeRetrievalHit(
        chunk_id=result.chunk_id,
        document_id=result.document_id,
        knowledge_base_id=result.knowledge_base_id,
        owner_user_id=result.owner_user_id,
        tenant_id=result.tenant_id,
        content=result.content,
        source=result.source,
        metadata=result.metadata,
        score=rerank_score,
        vector_rank=candidate.vector_rank,
        bm25_rank=candidate.bm25_rank,
        rerank_rank=rerank_rank,
        vector_score=candidate.vector_score,
        bm25_score=candidate.bm25_score,
        rrf_score=candidate.rrf_score,
        rerank_score=rerank_score,
    )


def _citation_from_hit(hit: KnowledgeRetrievalHit) -> KnowledgeRetrievalCitationSource:
    return KnowledgeRetrievalCitationSource(
        id=hit.chunk_id,
        title=hit.source or hit.document_id,
        source_type="knowledge-base",
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        knowledge_base_id=hit.knowledge_base_id,
        source=hit.source,
        metadata=hit.metadata,
        score=hit.score,
        excerpt=_citation_excerpt(hit.content),
        knowledge_type=_knowledge_type(hit),
        vector_rank=hit.vector_rank,
        bm25_rank=hit.bm25_rank,
        rerank_rank=hit.rerank_rank,
        vector_score=hit.vector_score,
        bm25_score=hit.bm25_score,
        rrf_score=hit.rrf_score,
        rerank_score=hit.rerank_score,
    )


def _filters_from_langchain(
    filters: LangChainKnowledgeRetrievalFilters | None,
) -> KnowledgeRetrievalFilters | None:
    if filters is None:
        return None
    return KnowledgeRetrievalFilters(
        knowledge_base_ids=tuple(filters.knowledge_base_ids),
        document_ids=tuple(filters.document_ids),
        metadata=filters.metadata,
    )


def _result_payload(result: KnowledgeRetrievalToolResult) -> dict[str, object]:
    return {
        "query": result.query,
        "topK": result.top_k,
        "results": [_hit_payload(hit) for hit in result.results],
        "citations": [_citation_payload(citation) for citation in result.citations],
    }


def _hit_payload(hit: KnowledgeRetrievalHit) -> dict[str, object]:
    return {
        "chunkId": hit.chunk_id,
        "documentId": hit.document_id,
        "knowledgeBaseId": hit.knowledge_base_id,
        "ownerUserId": hit.owner_user_id,
        "tenantId": hit.tenant_id,
        "content": hit.content,
        "source": hit.source,
        "metadata": dict(hit.metadata),
        "score": hit.score,
        "vectorRank": hit.vector_rank,
        "bm25Rank": hit.bm25_rank,
        "rerankRank": hit.rerank_rank,
        "vectorScore": hit.vector_score,
        "bm25Score": hit.bm25_score,
        "rrfScore": hit.rrf_score,
        "rerankScore": hit.rerank_score,
    }


def _citation_payload(citation: KnowledgeRetrievalCitationSource) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": citation.id,
        "title": citation.title,
        "sourceType": citation.source_type,
        "chunkId": citation.chunk_id,
        "documentId": citation.document_id,
        "knowledgeBaseId": citation.knowledge_base_id,
        "source": citation.source,
        "metadata": dict(citation.metadata),
        "score": citation.score,
        "vectorRank": citation.vector_rank,
        "bm25Rank": citation.bm25_rank,
        "rerankRank": citation.rerank_rank,
        "vectorScore": citation.vector_score,
        "bm25Score": citation.bm25_score,
        "rrfScore": citation.rrf_score,
        "rerankScore": citation.rerank_score,
        "excerpt": citation.excerpt,
        "knowledgeType": citation.knowledge_type,
    }
    if citation.uri is not None:
        payload["uri"] = citation.uri
    return payload


def _citation_excerpt(content: str) -> str:
    normalized = " ".join(content.split())
    if len(normalized) <= MAX_CITATION_EXCERPT_LENGTH:
        return normalized
    return f"{normalized[:MAX_CITATION_EXCERPT_LENGTH - 3]}..."


def _knowledge_type(hit: KnowledgeRetrievalHit) -> str:
    value = hit.metadata.get("knowledgeType", hit.metadata.get("kind"))
    if isinstance(value, str) and value in {"document", "sop", "diagnostic-case"}:
        return value
    if hit.source == "aiops-diagnostic":
        return "diagnostic-case"
    return "sop" if "sop" in hit.source.lower() else "document"
