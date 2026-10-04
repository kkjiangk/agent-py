"""Bounded, versioned lexical corpus cache shared by chat and diagnostics."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic

from super_ai.vector_store import StoredVectorChunk

from .hybrid import Bm25Index


@dataclass(frozen=True, slots=True)
class LexicalCacheKey:
    owner_user_id: str
    knowledge_base_ids: tuple[str, ...]
    document_ids: tuple[str, ...]
    metadata_json: str
    revision: str


@dataclass(frozen=True, slots=True)
class LexicalCorpus:
    chunks: tuple[StoredVectorChunk, ...]
    index: Bm25Index
    characters: int
    expires_at: float


class LexicalIndexCache:
    """Serialize cold builds, reuse warm indexes, and evict by LRU and text budget."""

    def __init__(
        self,
        *,
        max_entries: int = 32,
        max_characters: int = 32_000_000,
        ttl_seconds: float = 60,
    ) -> None:
        if max_entries < 1 or max_characters < 1 or ttl_seconds <= 0:
            raise ValueError("Lexical cache limits must be positive.")
        self._max_entries = max_entries
        self._max_characters = max_characters
        self._ttl_seconds = ttl_seconds
        self._entries: OrderedDict[LexicalCacheKey, LexicalCorpus] = OrderedDict()
        self._characters = 0
        self._build_lock = asyncio.Lock()

    async def get_or_load(
        self,
        key: LexicalCacheKey,
        loader: Callable[[], Awaitable[list[StoredVectorChunk]]],
    ) -> LexicalCorpus:
        cached = self._get(key)
        if cached is not None:
            return cached
        async with self._build_lock:
            cached = self._get(key)
            if cached is not None:
                return cached
            chunks = tuple(await loader())
            index = await asyncio.to_thread(Bm25Index, [chunk.content for chunk in chunks])
            corpus = LexicalCorpus(
                chunks=chunks,
                index=index,
                characters=sum(len(chunk.content) for chunk in chunks),
                expires_at=monotonic() + self._ttl_seconds,
            )
            # Oversized corpora remain queryable without retaining them in cache.
            if corpus.characters <= self._max_characters:
                while self._entries and (
                    len(self._entries) >= self._max_entries
                    or self._characters + corpus.characters > self._max_characters
                ):
                    _, removed = self._entries.popitem(last=False)
                    self._characters -= removed.characters
                self._entries[key] = corpus
                self._characters += corpus.characters
            return corpus

    def discard(self, key: LexicalCacheKey) -> None:
        removed = self._entries.pop(key, None)
        if removed is not None:
            self._characters -= removed.characters

    def _get(self, key: LexicalCacheKey) -> LexicalCorpus | None:
        cached = self._entries.get(key)
        if cached is not None and cached.expires_at <= monotonic():
            self.discard(key)
            return None
        if cached is not None:
            self._entries.move_to_end(key)
        return cached
