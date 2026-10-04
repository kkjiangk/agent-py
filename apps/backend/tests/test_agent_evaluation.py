from __future__ import annotations

import pytest

from super_ai.evaluation import EvaluationDataError, evaluate_records, render_markdown


def test_evaluation_reports_required_metrics_without_inventing_missing_cost() -> None:
    records = [
        _record("case-1", "db_pool_exhaustion", "db_pool_exhaustion", 100, True, 40, 20),
        _record("case-2", "cache_stampede", "cache_stampede", 200, False, 50, 25),
        _record("case-3", "queue_backlog", "network_timeout", 1000, False, 60, 60),
    ]
    records[2]["costUsd"] = None

    metrics = evaluate_records(records)
    markdown = render_markdown(metrics)

    assert metrics.sample_count == 3
    assert metrics.root_cause_accuracy == pytest.approx(2 / 3)
    assert metrics.baseline_root_cause_accuracy == pytest.approx(1 / 3)
    assert metrics.accuracy_improvement_percentage_points == pytest.approx(100 / 3)
    assert metrics.citation_correctness == pytest.approx(5 / 6)
    assert metrics.tool_call_success_rate == pytest.approx(2 / 3)
    assert metrics.latency_p50_ms == 200
    assert metrics.latency_p95_ms == 1000
    assert metrics.simulated_mttr_reduction == pytest.approx(45 / 150)
    assert metrics.average_cost_usd is None
    assert "Average cost: 未测量" in markdown


def test_evaluation_rejects_missing_predictions() -> None:
    record = _record("case-1", "db_pool_exhaustion", "db_pool_exhaustion", 100, True, 40, 20)
    del record["predictedRootCause"]

    with pytest.raises(EvaluationDataError, match="predictedRootCause"):
        evaluate_records([record])


def _record(
    case_id: str,
    expected: str,
    predicted: str,
    latency_ms: int,
    baseline_correct: bool,
    baseline_mttr: int,
    agent_mttr: int,
) -> dict[str, object]:
    return {
        "datasetVersion": "incidents-v1",
        "caseId": case_id,
        "expectedRootCause": expected,
        "predictedRootCause": predicted,
        "citations": [{"correct": True}, {"correct": case_id != "case-3"}],
        "toolCalls": [{"success": case_id != "case-3"}],
        "latencyMs": latency_ms,
        "agentCalls": 4,
        "promptTokens": 1000,
        "completionTokens": 500,
        "costUsd": 0.01,
        "baselineCorrect": baseline_correct,
        "baselineMttrMinutes": baseline_mttr,
        "simulatedMttrMinutes": agent_mttr,
    }
