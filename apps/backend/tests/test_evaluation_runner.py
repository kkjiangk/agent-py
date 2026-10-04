from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from super_ai.evaluation import EvaluationDataError, evaluate_records
from super_ai.evaluation_runner import (
    EvaluationRunSettings,
    IncidentEvaluationRunner,
    evaluation_query,
    extract_root_cause,
    safe_evaluation_trace,
    validate_evaluation_endpoint,
)

CASE: dict[str, object] = {
    "datasetVersion": "test-v1",
    "caseId": "case-1",
    "service": "payments",
    "alert": {"alertType": "timeout"},
    "expectedRootCause": "db_pool_exhaustion",
}


def envelope(data: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "data": data})


def test_prediction_requires_an_unambiguous_label_without_ground_truth_in_query() -> None:
    codes = ["db_pool_exhaustion", "cpu_saturation"]
    assert extract_root_cause("Maybe db_pool_exhaustion", allowed_codes=codes) == "unknown"
    assert extract_root_cause("ROOT_CAUSE: db_pool_exhaustion", allowed_codes=codes) == codes[0]
    assert extract_root_cause("ROOT_CAUSE: invalid", allowed_codes=codes) == "unknown"
    assert (
        extract_root_cause(
            "ROOT_CAUSE: db_pool_exhaustion\nROOT_CAUSE: cpu_saturation", allowed_codes=codes
        )
        == "unknown"
    )
    different = {**CASE, "expectedRootCause": "cpu_saturation"}
    assert evaluation_query(CASE, allowed_codes=codes) == evaluation_query(
        different, allowed_codes=codes
    )


def test_trace_omits_raw_tool_payloads_and_embedded_secrets() -> None:
    trace = safe_evaluation_trace(
        {
            "arguments": {"query": "private logs"},
            "output": "raw logs",
            "summary": "token=private-value",
            "authorization": "Bearer private-token",
        }
    )
    serialized = json.dumps(trace)
    assert "private" not in serialized
    assert "[omitted]" in serialized and "[redacted]" in serialized


def test_remote_evaluation_requires_explicit_secure_endpoint() -> None:
    validate_evaluation_endpoint("http://127.0.0.1:8000")
    validate_evaluation_endpoint("https://api.example.com", allow_remote=True)
    for url in ["http://api.example.com", "https://user:pass@api.example.com"]:
        with pytest.raises(ValueError):
            validate_evaluation_endpoint(url, allow_remote=True)
    with pytest.raises(ValueError):
        validate_evaluation_endpoint("https://api.example.com")


@pytest.mark.asyncio
async def test_workflow_runner_records_real_evidence_without_invented_usage() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            assert "expectedRootCause" not in body
            return envelope({"id": "task-1"})
        if request.url.path.endswith("evidence-chain"):
            return envelope(
                {
                    "reports": [{"content": "ROOT_CAUSE: db_pool_exhaustion"}],
                    "toolCalls": [{"id": "tool-1", "status": "completed", "arguments": "secret"}],
                    "evidence": [{"id": "evidence-1", "kind": "logs"}],
                }
            )
        return envelope({"status": "succeeded"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://test"
    ) as client:
        result = await IncidentEvaluationRunner(
            client, EvaluationRunSettings("workflow", "model-v1", "config-v1", "prompt-v1")
        ).run_case(CASE, allowed_codes=["db_pool_exhaustion"])
    assert result["status"] == "completed"
    assert result["predictedRootCause"] == "db_pool_exhaustion"
    assert result["toolCalls"] == [{"id": "tool-1", "success": True}]
    metrics = evaluate_records([result])
    assert metrics.root_cause_accuracy == 1
    assert metrics.average_tokens is None and metrics.average_cost_usd is None
    assert metrics.average_agent_calls is None and metrics.citation_correctness is None


@pytest.mark.asyncio
async def test_timeout_cancels_the_created_durable_job_and_records_failure() -> None:
    cancelled: list[str] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(":cancel"):
            cancelled.append(request.url.path)
            return envelope({})
        if request.method == "POST":
            return envelope({"id": "task-1", "backgroundJob": {"id": "job-1"}})
        await asyncio.sleep(0.1)
        return envelope({"status": "running"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://test"
    ) as client:
        result = await IncidentEvaluationRunner(
            client, EvaluationRunSettings("workflow", "m", "c", "p", timeout_seconds=0.01)
        ).run_case(CASE, allowed_codes=["db_pool_exhaustion"])
    assert cancelled == ["/background-jobs/job-1:cancel"]
    assert result["status"] == "failed" and result["errorCategory"] == "TimeoutError"
    assert result["predictedRootCause"] == "unknown"


@pytest.mark.asyncio
async def test_single_agent_uses_the_stream_and_removes_its_temporary_session() -> None:
    deleted: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            deleted.append(request.url.path)
            return envelope({})
        if request.url.path.endswith("messages:stream"):
            events = [
                {"type": "content.delta", "delta": "ROOT_CAUSE: db_pool_exhaustion"},
                {"type": "complete"},
            ]
            return httpx.Response(
                200,
                text="\n\n".join(f"data: {json.dumps(event)}" for event in events),
                headers={"content-type": "text/event-stream"},
            )
        return envelope({"id": "session-1"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="http://test"
    ) as client:
        result = await IncidentEvaluationRunner(
            client, EvaluationRunSettings("single-agent", "m", "c", "p")
        ).run_case(CASE, allowed_codes=["db_pool_exhaustion"])
    assert deleted == ["/chat/sessions/session-1"]
    assert result["predictedRootCause"] == "db_pool_exhaustion"


@pytest.mark.parametrize("invalid", [True, float("nan"), float("inf"), -1])
def test_metrics_reject_invalid_measurements(invalid: object) -> None:
    with pytest.raises(EvaluationDataError):
        evaluate_records([{**CASE, "predictedRootCause": "unknown", "latencyMs": invalid}])
