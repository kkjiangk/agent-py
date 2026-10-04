"""Offline, reproducible metrics for incident-response Agent evaluations."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, median
from typing import cast


class EvaluationDataError(ValueError):
    """Raised when an evaluation record cannot be measured safely."""


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    dataset_version: str
    sample_count: int
    root_cause_accuracy: float
    baseline_root_cause_accuracy: float | None
    accuracy_improvement_percentage_points: float | None
    citation_correctness: float | None
    tool_call_success_rate: float | None
    latency_p50_ms: float
    latency_p95_ms: float
    average_agent_calls: float | None
    average_tokens: float | None
    average_cost_usd: float | None
    simulated_mttr_reduction: float | None
    generated_at: str

    def to_json_dict(self) -> dict[str, object]:
        return cast(dict[str, object], asdict(self))


def load_evaluation_records(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvaluationDataError(f"Invalid JSON on line {line_number}.") from exc
        if not isinstance(value, dict):
            raise EvaluationDataError(f"Line {line_number} must be an object.")
        record = cast(dict[str, object], value)
        _validate_record(record, line_number)
        records.append(record)
    if not records:
        raise EvaluationDataError("Evaluation dataset is empty.")
    versions = {_required_str(record, "datasetVersion", 0) for record in records}
    if len(versions) != 1:
        raise EvaluationDataError("All records must use one datasetVersion.")
    return records


def evaluate_records(records: list[dict[str, object]]) -> EvaluationMetrics:
    if not records:
        raise EvaluationDataError("Evaluation dataset is empty.")
    for index, record in enumerate(records, start=1):
        _validate_record(record, index)
    correct = [
        _normalized(_required_str(record, "expectedRootCause", index))
        == _normalized(_required_str(record, "predictedRootCause", index))
        for index, record in enumerate(records, start=1)
    ]
    baseline_values = [record.get("baselineCorrect") for record in records]
    baseline_accuracy = (
        fmean(1.0 if value else 0.0 for value in baseline_values)
        if all(isinstance(value, bool) for value in baseline_values)
        else None
    )
    citation_values = _nested_booleans(records, "citations", "correct")
    tool_values = _nested_booleans(records, "toolCalls", "success")
    latencies = [
        _required_number(record, "latencyMs", index) for index, record in enumerate(records, 1)
    ]
    calls = _complete_measurements(records, ("agentCalls",))
    tokens = _complete_measurements(records, ("promptTokens", "completionTokens"))
    costs = [record.get("costUsd") for record in records]
    average_cost = (
        fmean(float(value) for value in costs if isinstance(value, (int, float)))
        if all(_is_number(value) for value in costs)
        else None
    )
    baseline_mttr = [record.get("baselineMttrMinutes") for record in records]
    agent_mttr = [record.get("simulatedMttrMinutes") for record in records]
    mttr_reduction: float | None = None
    if all(_is_number(value) for value in baseline_mttr + agent_mttr):
        baseline_total = sum(float(cast(float, value)) for value in baseline_mttr)
        agent_total = sum(float(cast(float, value)) for value in agent_mttr)
        if baseline_total > 0:
            mttr_reduction = (baseline_total - agent_total) / baseline_total
    accuracy = fmean(1.0 if value else 0.0 for value in correct)
    return EvaluationMetrics(
        dataset_version=_required_str(records[0], "datasetVersion", 1),
        sample_count=len(records),
        root_cause_accuracy=accuracy,
        baseline_root_cause_accuracy=baseline_accuracy,
        accuracy_improvement_percentage_points=(
            (accuracy - baseline_accuracy) * 100 if baseline_accuracy is not None else None
        ),
        citation_correctness=(
            fmean(1.0 if value else 0.0 for value in citation_values) if citation_values else None
        ),
        tool_call_success_rate=(
            fmean(1.0 if value else 0.0 for value in tool_values) if tool_values else None
        ),
        latency_p50_ms=median(latencies),
        latency_p95_ms=_percentile(latencies, 0.95),
        average_agent_calls=fmean(calls) if calls is not None else None,
        average_tokens=fmean(tokens) if tokens is not None else None,
        average_cost_usd=average_cost,
        simulated_mttr_reduction=mttr_reduction,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def render_markdown(metrics: EvaluationMetrics) -> str:
    def percent(value: float | None) -> str:
        return "未测量" if value is None else f"{value * 100:.2f}%"

    cost = "未测量" if metrics.average_cost_usd is None else f"${metrics.average_cost_usd:.6f}"
    improvement = (
        "未测量"
        if metrics.accuracy_improvement_percentage_points is None
        else f"{metrics.accuracy_improvement_percentage_points:.2f} pp"
    )
    calls = (
        "未测量" if metrics.average_agent_calls is None else f"{metrics.average_agent_calls:.2f}"
    )
    tokens = "未测量" if metrics.average_tokens is None else f"{metrics.average_tokens:.2f}"
    return "\n".join(
        [
            "# Agent Evaluation Report",
            "",
            f"- Dataset: `{metrics.dataset_version}`",
            f"- Samples: {metrics.sample_count}",
            f"- Root-cause accuracy: {percent(metrics.root_cause_accuracy)}",
            f"- Single-Agent baseline accuracy: {percent(metrics.baseline_root_cause_accuracy)}",
            f"- Accuracy improvement: {improvement}",
            f"- Citation correctness: {percent(metrics.citation_correctness)}",
            f"- Tool-call success rate: {percent(metrics.tool_call_success_rate)}",
            f"- Latency P50/P95: {metrics.latency_p50_ms:.2f} / {metrics.latency_p95_ms:.2f} ms",
            f"- Average Agent calls: {calls}",
            f"- Average tokens: {tokens}",
            f"- Average cost: {cost}",
            f"- Simulated MTTR reduction: {percent(metrics.simulated_mttr_reduction)}",
            "",
            "Results are valid only for the dataset version and sample count shown above.",
        ]
    )


def _validate_record(record: dict[str, object], line_number: int) -> None:
    for key in ("datasetVersion", "caseId", "expectedRootCause", "predictedRootCause"):
        _required_str(record, key, line_number)
    for key in (
        "latencyMs",
        "agentCalls",
        "promptTokens",
        "completionTokens",
        "costUsd",
        "baselineMttrMinutes",
        "simulatedMttrMinutes",
    ):
        if key != "latencyMs" and record.get(key) is None:
            continue
        value = _required_number(record, key, line_number)
        if value < 0:
            raise EvaluationDataError(f"Line {line_number} field {key} must be non-negative.")


def _required_str(record: dict[str, object], key: str, line_number: int) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EvaluationDataError(f"Line {line_number} requires non-empty {key}.")
    return value.strip()


def _required_number(record: dict[str, object], key: str, line_number: int) -> float:
    value = record.get(key)
    if not _is_number(value):
        raise EvaluationDataError(f"Line {line_number} requires numeric {key}.")
    return float(cast(float, value))


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _complete_measurements(
    records: list[dict[str, object]], fields: tuple[str, ...]
) -> list[float] | None:
    if not all(_is_number(record.get(field)) for record in records for field in fields):
        return None
    return [sum(float(cast(float, record[field])) for field in fields) for record in records]


def _nested_booleans(
    records: list[dict[str, object]], collection_key: str, value_key: str
) -> list[bool]:
    values: list[bool] = []
    for record in records:
        collection = record.get(collection_key)
        if not isinstance(collection, list):
            continue
        for item in cast(list[object], collection):
            if isinstance(item, dict):
                value = cast(dict[str, object], item).get(value_key)
                if isinstance(value, bool):
                    values.append(value)
    return values


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())
