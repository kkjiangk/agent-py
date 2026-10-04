from __future__ import annotations

import json

import httpx
import pytest

from super_ai.llm import LlmRerankError, QwenVlRerankModel


@pytest.mark.asyncio
async def test_qwen_rerank_sends_expected_request_and_sorts_results() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "output": {
                    "results": [
                        {"index": 0, "relevance_score": 0.41},
                        {"index": 1, "relevance_score": 0.96},
                    ]
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = QwenVlRerankModel(
            api_key="test-secret",
            endpoint="https://example.test/rerank",
            model="qwen3-vl-rerank",
            timeout_seconds=10,
            max_retries=0,
            client=client,
        )
        results = await model.arerank(
            query="restart api",
            documents=["weather", "api restart runbook"],
            top_n=2,
        )

    assert [(item.index, item.relevance_score) for item in results] == [
        (1, 0.96),
        (0, 0.41),
    ]
    assert captured["authorization"] == "Bearer test-secret"
    assert captured["payload"] == {
        "model": "qwen3-vl-rerank",
        "input": {
            "query": {"text": "restart api"},
            "documents": [{"text": "weather"}, {"text": "api restart runbook"}],
        },
        "parameters": {"return_documents": False, "top_n": 2},
    }


@pytest.mark.asyncio
async def test_qwen_rerank_rejects_invalid_provider_response_safely() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"output": {"results": [{"index": 7, "relevance_score": 0.9}]}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = QwenVlRerankModel(
            api_key="test-secret",
            endpoint="https://example.test/rerank",
            model="qwen3-vl-rerank",
            timeout_seconds=10,
            max_retries=0,
            client=client,
        )
        with pytest.raises(LlmRerankError, match="invalid response") as exc_info:
            await model.arerank(query="query", documents=["one"], top_n=1)

    assert "test-secret" not in str(exc_info.value)
