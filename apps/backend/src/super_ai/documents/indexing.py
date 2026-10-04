"""Document chunking and non-blocking indexing service."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Protocol, cast

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from super_ai.llm import EmbeddingModel
from super_ai.memory.repositories import (
    DocumentIndexTaskRecord,
    KnowledgeDocumentRecord,
    MemoryRepositories,
    TenantScopeError,
)
from super_ai.memory.vector_scope import build_vector_chunk_metadata
from super_ai.observability import elapsed_ms, emit_event
from super_ai.vector_store import VectorChunkRecord

DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 200
logger = logging.getLogger(__name__)


class DocumentIndexingError(RuntimeError):
    """Raised when a document cannot be indexed safely."""


class IndexVectorStore(Protocol):
    """Vector store operations needed by document indexing."""

    def initialize(self) -> None:
        """Ensure the vector collection and indexes exist before writes."""
        ...

    def delete_document_chunks(
        self,
        *,
        tenant_id: str,
        knowledge_base_id: str,
        document_id: str,
    ) -> None:
        """Delete existing scoped chunks before rebuilding a document index."""
        ...

    def insert_chunks(self, chunks: Sequence[VectorChunkRecord]) -> None:
        """Insert indexed chunks."""
        ...


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    """Deterministic chunk of indexable document text."""

    index: int
    content: str
    start: int
    end: int
    heading_path: str | None = None

    @property
    def metadata(self) -> dict[str, int | str]:
        metadata: dict[str, int | str] = {
            "chunkIndex": self.index,
            "start": self.start,
            "end": self.end,
        }
        if self.heading_path is not None:
            metadata["headingPath"] = self.heading_path
        return metadata


class DocumentIndexingService:
    """Run one document index task through chunk, embed, and Milvus insert steps."""

    def __init__(
        self,
        *,
        repositories: MemoryRepositories,
        embedding_model: EmbeddingModel,
        vector_store: IndexVectorStore,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> None:
        self._repositories = repositories
        self._embedding_model = embedding_model
        self._vector_store = vector_store
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    async def run_task(self, *, owner_user_id: str, task_id: str) -> DocumentIndexTaskRecord:
        """Run a persisted index task and return its final state."""
        started_at = monotonic()
        task = await self._repositories.document_index_tasks.get_task(
            owner_user_id=owner_user_id,
            task_id=task_id,
        )
        if task is None:
            raise TenantScopeError(f"Document index task is not accessible: {task_id}")
        emit_event(
            logger,
            "index.task.started",
            taskId=task.id,
            documentId=task.document_id,
        )

        await self._repositories.document_index_tasks.mark_running(
            owner_user_id=owner_user_id,
            task_id=task.id,
        )
        await self._repositories.documents.update_index_status(
            owner_user_id=owner_user_id,
            knowledge_base_id=task.knowledge_base_id,
            document_id=task.document_id,
            index_status="indexing",
        )

        try:
            document = await self._load_document(owner_user_id=owner_user_id, task=task)
            strategy, chunk_size, chunk_overlap = _chunking_kwargs(
                document, self._chunk_size, self._chunk_overlap
            )
            chunks = chunk_document_text(
                _indexable_text(document),
                strategy=strategy,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            if not chunks:
                raise DocumentIndexingError("Document has no indexable text.")
            vectors = await self._embedding_model.aembed_documents(
                [chunk.content for chunk in chunks]
            )
            if len(vectors) != len(chunks):
                raise DocumentIndexingError(
                    "Embedding provider returned an unexpected vector count."
                )
            self._vector_store.initialize()
            self._vector_store.delete_document_chunks(
                tenant_id=owner_user_id,
                knowledge_base_id=document.knowledge_base_id,
                document_id=document.id,
            )
            self._vector_store.insert_chunks(
                [
                    _vector_chunk_record(
                        document=document,
                        tenant_id=owner_user_id,
                        chunk=chunk,
                        vector=vector,
                    )
                    for chunk, vector in zip(chunks, vectors, strict=True)
                ]
            )
        except Exception as exc:
            reason = _safe_failure_reason(exc)
            await self._repositories.documents.update_index_status(
                owner_user_id=owner_user_id,
                knowledge_base_id=task.knowledge_base_id,
                document_id=task.document_id,
                index_status="failed",
            )
            failed = await self._repositories.document_index_tasks.mark_failed(
                owner_user_id=owner_user_id,
                task_id=task.id,
                failure_reason=reason,
            )
            if failed is None:
                raise
            emit_event(
                logger,
                "index.task.failed",
                taskId=task.id,
                documentId=task.document_id,
                errorCategory=exc.__class__.__name__,
                durationMs=elapsed_ms(started_at),
            )
            return failed

        await self._repositories.documents.update_index_status(
            owner_user_id=owner_user_id,
            knowledge_base_id=task.knowledge_base_id,
            document_id=task.document_id,
            index_status="indexed",
        )
        succeeded = await self._repositories.document_index_tasks.mark_succeeded(
            owner_user_id=owner_user_id,
            task_id=task.id,
        )
        if succeeded is None:
            raise TenantScopeError(f"Document index task is not accessible: {task.id}")
        emit_event(
            logger,
            "index.task.completed",
            taskId=task.id,
            documentId=task.document_id,
            chunkCount=len(chunks),
            durationMs=elapsed_ms(started_at),
        )
        return succeeded

    async def _load_document(
        self,
        *,
        owner_user_id: str,
        task: DocumentIndexTaskRecord,
    ) -> KnowledgeDocumentRecord:
        document = await self._repositories.documents.get_document(
            owner_user_id=owner_user_id,
            knowledge_base_id=task.knowledge_base_id,
            document_id=task.document_id,
        )
        if document is None:
            raise TenantScopeError(f"Document is not accessible: {task.document_id}")
        return document


def chunk_document_text(
    text: str,
    *,
    strategy: str = "legacy-word",
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[DocumentChunk]:
    """Split text deterministically using the document's persisted strategy."""
    effective_chunk_size = DEFAULT_CHUNK_SIZE if chunk_size is None else chunk_size
    effective_chunk_overlap = chunk_overlap if chunk_overlap is not None else DEFAULT_CHUNK_OVERLAP
    if effective_chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")
    if effective_chunk_overlap < 0:
        raise ValueError("chunk_overlap must be zero or greater")

    normalized = text.strip()
    if not normalized:
        return []
    if strategy == "markdown-heading":
        return _heading_chunks(normalized, effective_chunk_size)
    if strategy == "paragraph":
        return _paragraph_chunks(normalized, effective_chunk_size)
    if strategy == "legacy-word":
        return _legacy_word_chunks(normalized, effective_chunk_size)
    if strategy != "fixed-character":
        raise ValueError("Unsupported chunking strategy")
    if effective_chunk_overlap >= effective_chunk_size:
        raise ValueError("chunk_overlap must be smaller than chunk_size")
    return _fixed_chunks(normalized, effective_chunk_size, effective_chunk_overlap)


def _fixed_chunks(text: str, chunk_size: int, chunk_overlap: int) -> list[DocumentChunk]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )
    return _chunks_from_contents(
        splitter.split_text(text),
        text,
        chunk_overlap=chunk_overlap,
    )


def _legacy_word_chunks(text: str, chunk_size: int) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    current: list[str] = []
    start = 0
    cursor = 0
    for word in text.split():
        word_start = text.find(word, cursor)
        candidate = " ".join([*current, word])
        if current and len(candidate) > chunk_size:
            content = " ".join(current)
            chunks.append(DocumentChunk(len(chunks), content, start, start + len(content)))
            current = [word]
            start = word_start
        else:
            if not current:
                start = word_start
            current.append(word)
        cursor = word_start + len(word)
    if current:
        content = " ".join(current)
        chunks.append(DocumentChunk(len(chunks), content, start, start + len(content)))
    return chunks


def _paragraph_chunks(text: str, chunk_size: int) -> list[DocumentChunk]:
    paragraphs = [item.strip() for item in text.split("\n\n") if item.strip()]
    return _group_units(paragraphs, text, chunk_size, None)


def _heading_chunks(text: str, chunk_size: int) -> list[DocumentChunk]:
    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "h1"),
            ("##", "h2"),
            ("###", "h3"),
            ("####", "h4"),
            ("#####", "h5"),
            ("######", "h6"),
        ],
        strip_headers=False,
    )
    documents = splitter.split_text(text)
    chunks: list[DocumentChunk] = []
    cursor = 0
    for document in documents:
        content = document.page_content.strip()
        if not content:
            continue
        heading_path = _heading_path(document.metadata)
        start = text.find(content, cursor)
        start = start if start >= 0 else text.find(content)
        start = max(start, 0)
        if len(content) > chunk_size:
            for chunk in _fixed_chunks(content, chunk_size, 0):
                chunks.append(
                    DocumentChunk(
                        len(chunks),
                        chunk.content,
                        start + chunk.start,
                        start + chunk.end,
                        heading_path,
                    )
                )
        else:
            chunks.append(
                DocumentChunk(
                    len(chunks),
                    content,
                    start,
                    start + len(content),
                    heading_path,
                )
            )
        cursor = start + len(content)
    if chunks:
        return chunks
    return _group_units([text], text, chunk_size, "heading")


def _chunks_from_contents(
    contents: Sequence[str],
    original: str,
    *,
    chunk_overlap: int,
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    cursor = 0
    for raw_content in contents:
        content = raw_content.strip()
        if not content:
            continue
        start = original.find(content, cursor)
        if start < 0:
            start = original.find(content)
        start = max(start, 0)
        chunks.append(DocumentChunk(len(chunks), content, start, start + len(content)))
        cursor = max(start + 1, start + len(content) - chunk_overlap)
    return chunks


def _heading_path(metadata: Mapping[str, object]) -> str | None:
    parts = [
        value
        for key in ("h1", "h2", "h3", "h4", "h5", "h6")
        if isinstance((value := metadata.get(key)), str)
    ]
    if not parts:
        return None
    return " / ".join(parts)


def _group_units(
    units: list[str], original: str, chunk_size: int, kind: str | None
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    current = ""
    cursor = 0
    for unit in units:
        candidate = f"{current}\n\n{unit}" if current else unit
        if current and len(candidate) > chunk_size:
            start = original.find(current, cursor)
            chunks.append(
                DocumentChunk(
                    len(chunks),
                    current,
                    max(start, 0),
                    max(start, 0) + len(current),
                    current.splitlines()[0] if kind else None,
                )
            )
            cursor = max(start, 0) + len(current)
            current = unit
        else:
            current = candidate
    if current:
        start = original.find(current, cursor)
        if len(current) > chunk_size:
            for chunk in _fixed_chunks(current, chunk_size, 0):
                chunks.append(
                    DocumentChunk(
                        len(chunks),
                        chunk.content,
                        max(start, 0) + chunk.start,
                        max(start, 0) + chunk.end,
                        current.splitlines()[0] if kind else None,
                    )
                )
        else:
            chunks.append(
                DocumentChunk(
                    len(chunks),
                    current,
                    max(start, 0),
                    max(start, 0) + len(current),
                    current.splitlines()[0] if kind else None,
                )
            )
    return chunks


def _indexable_text(document: KnowledgeDocumentRecord) -> str:
    value = document.metadata.get("indexableText")
    if isinstance(value, str):
        return value
    return ""


def _chunking_kwargs(
    document: KnowledgeDocumentRecord,
    default_size: int = DEFAULT_CHUNK_SIZE,
    default_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> tuple[str, int, int]:
    value = document.metadata.get("chunking")
    if not isinstance(value, dict):
        return "legacy-word", default_size, default_overlap
    mapping = cast(dict[str, object], value)
    strategy = str(mapping.get("strategy", "fixed-character"))
    if strategy == "fixed-character":
        return (
            strategy,
            int(cast(int, mapping.get("maxCharacters", default_size))),
            int(cast(int, mapping.get("overlapCharacters", default_overlap))),
        )
    return strategy, default_size, 0


def _chunking_parameters(document: KnowledgeDocumentRecord) -> dict[str, object]:
    strategy, chunk_size, chunk_overlap = _chunking_kwargs(document)
    if strategy == "fixed-character":
        return {
            "strategy": strategy,
            "maxCharacters": chunk_size,
            "overlapCharacters": chunk_overlap,
        }
    return {"strategy": strategy}


def _vector_chunk_record(
    *,
    document: KnowledgeDocumentRecord,
    tenant_id: str,
    chunk: DocumentChunk,
    vector: Sequence[float],
) -> VectorChunkRecord:
    chunk_id = f"{document.id}_chunk_{chunk.index:04d}"
    metadata: dict[str, object] = {
        **chunk.metadata,
        "knowledgeType": _knowledge_type(document),
        "chunkingStrategy": _chunking_kwargs(document)[0],
        "chunkingParameters": _chunking_parameters(document),
        **build_vector_chunk_metadata(
            owner_user_id=document.owner_user_id,
            tenant_id=tenant_id,
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
            chunk_id=chunk_id,
        ),
    }
    return VectorChunkRecord(
        chunk_id=chunk_id,
        document_id=document.id,
        knowledge_base_id=document.knowledge_base_id,
        owner_user_id=document.owner_user_id,
        tenant_id=tenant_id,
        content=chunk.content,
        vector=vector,
        metadata=metadata,
        source=document.source or document.filename,
        created_at=datetime.now(timezone.utc),
    )


def _knowledge_type(document: KnowledgeDocumentRecord) -> str:
    explicit = document.metadata.get("knowledgeType", document.metadata.get("kind"))
    if isinstance(explicit, str) and explicit in {"document", "sop", "diagnostic-case"}:
        return explicit
    if document.source == "aiops-diagnostic":
        return "diagnostic-case"
    source_text = f"{document.filename} {document.source or ''}".lower()
    return "sop" if "sop" in source_text else "document"


def _safe_failure_reason(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        message = exc.__class__.__name__
    return message[:500]
