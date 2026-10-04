"""Async rerank boundary backed by Alibaba Cloud Model Studio."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

import httpx


@dataclass(frozen=True, slots=True)
class RerankResult:
    """One validated rerank result referencing an input document index."""

    index: int
    relevance_score: float


class RerankModel(Protocol):
    """Provider-neutral async text reranking boundary."""

    async def arerank(
        self,
        *,
        query: str,
        documents: Sequence[str],
        top_n: int,
    ) -> list[RerankResult]:
        """Rank documents for a query and return input indexes."""
        ...


class LlmRerankError(RuntimeError):
    """Safe rerank failure without provider response details."""


class QwenVlRerankModel:
    """Alibaba Cloud qwen3-vl-rerank HTTP client."""

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._endpoint = endpoint
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._client = client

    async def arerank(
        self,
        *,
        query: str,
        documents: Sequence[str],
        top_n: int,
    ) -> list[RerankResult]:
        normalized_query = query.strip()
        if not normalized_query or not documents:
            return []
        if top_n < 1 or top_n > len(documents):
            raise LlmRerankError("Rerank request is invalid.")

        payload = {
            "model": self._model,
            "input": {
                "query": {"text": normalized_query},
                "documents": [{"text": document} for document in documents],
            },
            "parameters": {"return_documents": False, "top_n": top_n},
        }
        response = await self._post_with_retry(payload)
        return _parse_rerank_results(response, document_count=len(documents), top_n=top_n)

    async def _post_with_retry(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        for attempt in range(self._max_retries + 1):
            try:
                if self._client is not None:
                    response = await self._client.post(
                        self._endpoint,
                        headers=headers,
                        json=payload,
                        timeout=self._timeout_seconds,
                    )
                else:
                    async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                        response = await client.post(
                            self._endpoint,
                            headers=headers,
                            json=payload,
                        )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self._max_retries:
                        await asyncio.sleep(0.25 * (2**attempt))
                        continue
                response.raise_for_status()
                parsed: object = response.json()
                if not isinstance(parsed, Mapping):
                    raise ValueError("Rerank response is not an object.")
                return cast(Mapping[str, object], parsed)
            except (httpx.HTTPError, ValueError) as exc:
                if attempt < self._max_retries and isinstance(
                    exc, (httpx.TransportError, httpx.TimeoutException)
                ):
                    await asyncio.sleep(0.25 * (2**attempt))
                    continue
                raise LlmRerankError("Rerank service is temporarily unavailable.") from exc
        raise LlmRerankError("Rerank service is temporarily unavailable.")


def _parse_rerank_results(
    payload: Mapping[str, object], *, document_count: int, top_n: int
) -> list[RerankResult]:
    output = payload.get("output")
    if not isinstance(output, Mapping):
        raise LlmRerankError("Rerank service returned an invalid response.")
    raw_results = cast(Mapping[str, object], output).get("results")
    if not isinstance(raw_results, list):
        raise LlmRerankError("Rerank service returned an invalid response.")

    results: list[RerankResult] = []
    seen_indexes: set[int] = set()
    for raw_result in cast(list[object], raw_results):
        if not isinstance(raw_result, Mapping):
            raise LlmRerankError("Rerank service returned an invalid response.")
        result = cast(Mapping[str, object], raw_result)
        index = result.get("index")
        score = result.get("relevance_score")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index >= document_count
            or index in seen_indexes
            or not isinstance(score, int | float)
            or isinstance(score, bool)
        ):
            raise LlmRerankError("Rerank service returned an invalid response.")
        relevance_score = float(score)
        if not math.isfinite(relevance_score) or not 0 <= relevance_score <= 1:
            raise LlmRerankError("Rerank service returned an invalid response.")
        seen_indexes.add(index)
        results.append(RerankResult(index=index, relevance_score=relevance_score))

    results.sort(key=lambda item: item.relevance_score, reverse=True)
    return results[:top_n]
