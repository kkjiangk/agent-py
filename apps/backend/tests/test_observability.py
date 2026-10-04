from __future__ import annotations

import json
import logging

import httpx
import pytest

from super_ai.api.app import create_app
from super_ai.vector_store import MilvusHealthCheckResult


class FakeVectorStore:
    def health_check(self) -> MilvusHealthCheckResult:
        return MilvusHealthCheckResult(True, "http://milvus.test", "chunks", 1.0)


def test_application_enables_structured_event_logger_by_default() -> None:
    create_app(vector_store=FakeVectorStore())

    structured_logger = logging.getLogger("super_ai")
    assert structured_logger.getEffectiveLevel() <= logging.INFO
    assert any(
        handler.get_name() == "super_ai_structured_events"
        for handler in structured_logger.handlers
    )


@pytest.mark.asyncio
async def test_request_observability_preserves_correlation_and_aggregates_metrics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="super_ai.api.app")
    app = create_app(vector_store=FakeVectorStore())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/metrics",
            headers={"Authorization": "Bearer request-secret", "X-Request-ID": "request-test"},
        )
        denied = await client.get("/auth/me", headers={"X-Request-ID": "request-error"})
        metrics = await client.get("/metrics")

    assert response.headers["X-Request-ID"] == "request-test"
    assert denied.status_code == 401
    assert metrics.json()["data"]["requestCount"] >= 1
    events = [
        json.loads(record.message) for record in caplog.records if record.message.startswith("{")
    ]
    completion = next(event for event in events if event["event"] == "request.complete")
    error = next(event for event in events if event["event"] == "request.error")
    assert completion["requestId"] == "request-test"
    assert error == {
        "errorCode": "AUTH_UNAUTHENTICATED",
        "event": "request.error",
        "requestId": "request-error",
    }
    assert "request-secret" not in "\n".join(record.message for record in caplog.records)
