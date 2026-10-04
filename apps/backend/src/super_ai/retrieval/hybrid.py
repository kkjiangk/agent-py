"""Lexical retrieval and rank fusion primitives for hybrid knowledge search."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol, cast

BM25_CANDIDATE_LIMIT = 20
RRF_K = 60

_TOKEN_PATTERN = re.compile(
    r"[A-Za-z0-9]+(?:[._:/-][A-Za-z0-9]+)*|[\u3400-\u4dbf\u4e00-\u9fff]+"
)


class _Bm25Scorer(Protocol):
    def get_scores(self, query: Sequence[str]) -> Sequence[float]:
        """Return one score per corpus document."""
        ...


@dataclass(frozen=True, slots=True)
class Bm25Rank:
    """One lexical rank pointing back to the input document sequence."""

    index: int
    score: float


@dataclass(frozen=True, slots=True)
class ReciprocalRank:
    """One fused rank with optional source-list positions."""

    key: str
    score: float
    vector_rank: int | None
    bm25_rank: int | None


def tokenize_hybrid_text(text: str) -> list[str]:
    """Tokenize mixed Chinese and operational ASCII text deterministically."""
    tokens: list[str] = []
    for match in _TOKEN_PATTERN.finditer(text):
        value = match.group(0).lower()
        if _is_chinese_segment(value):
            characters = list(value)
            tokens.extend(characters)
            tokens.extend(
                "".join(characters[index : index + 2])
                for index in range(len(characters) - 1)
            )
        else:
            tokens.append(value)
    return tokens


def rank_bm25_documents(
    *,
    query: str,
    documents: Sequence[str],
    limit: int = BM25_CANDIDATE_LIMIT,
) -> list[Bm25Rank]:
    """Rank documents with BM25 while excluding documents with no token overlap."""
    return Bm25Index(documents).rank(query=query, limit=limit)


class Bm25Index:
    """Reusable BM25L corpus; queries preserve the uncached ranking semantics."""

    def __init__(self, documents: Sequence[str]) -> None:
        tokens = [tokenize_hybrid_text(document) for document in documents]
        self._token_sets = [frozenset(document) for document in tokens]
        self._scorer = _create_bm25_scorer(tokens) if any(tokens) else None

    def rank(self, *, query: str, limit: int = BM25_CANDIDATE_LIMIT) -> list[Bm25Rank]:
        query_tokens = tokenize_hybrid_text(query)
        if not query_tokens or self._scorer is None or limit < 1:
            return []
        scores = self._scorer.get_scores(query_tokens)
        query_token_set = set(query_tokens)
        ranks = [
            Bm25Rank(index=index, score=float(scores[index]))
            for index, tokens in enumerate(self._token_sets)
            if query_token_set.intersection(tokens)
        ]
        ranks.sort(key=lambda item: (-item.score, item.index))
        return ranks[:limit]


def reciprocal_rank_fusion(
    *,
    vector_keys: Sequence[str],
    bm25_keys: Sequence[str],
    limit: int,
    k: int = RRF_K,
) -> list[ReciprocalRank]:
    """Fuse two ranked key lists with deterministic Reciprocal Rank Fusion."""
    if k < 1:
        raise ValueError("RRF k must be greater than zero")
    positions: dict[str, dict[str, int]] = {}
    for source, keys in (("vector", vector_keys), ("bm25", bm25_keys)):
        for rank, key in enumerate(dict.fromkeys(keys), start=1):
            positions.setdefault(key, {})[source] = rank

    fused = [
        ReciprocalRank(
            key=key,
            score=sum(1 / (k + rank) for rank in source_positions.values()),
            vector_rank=source_positions.get("vector"),
            bm25_rank=source_positions.get("bm25"),
        )
        for key, source_positions in positions.items()
    ]
    fused.sort(
        key=lambda item: (
            -item.score,
            min(rank for rank in (item.vector_rank, item.bm25_rank) if rank is not None),
            item.key,
        )
    )
    return fused[: max(limit, 0)]


def _create_bm25_scorer(corpus_tokens: Sequence[Sequence[str]]) -> _Bm25Scorer:
    module: Any = import_module("rank_bm25")
    scorer_type: Any = module.BM25L
    return cast(_Bm25Scorer, scorer_type(corpus_tokens))


def _is_chinese_segment(value: str) -> bool:
    return bool(value) and "\u3400" <= value[0] <= "\u9fff"
