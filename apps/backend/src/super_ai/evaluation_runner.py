"""Execute incident evaluations against an explicitly selected authenticated API."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from time import monotonic
from typing import Literal, cast
from urllib.parse import urlsplit

import httpx

from super_ai.deployment import object_value, objects


@dataclass(frozen=True, slots=True)
class EvaluationRunSettings:
    mode: Literal["workflow", "single-agent"]
    model_version: str
    config_version: str
    prompt_version: str
    timeout_seconds: float = 900
    poll_seconds: float = 0.5


def validate_evaluation_endpoint(url: str, *, allow_remote: bool = False) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username:
        raise ValueError("Evaluation requires an HTTP API URL without embedded credentials.")
    if parts.hostname not in {"localhost", "127.0.0.1", "::1"}:
        if not allow_remote or parts.scheme != "https":
            raise ValueError("Remote evaluation requires explicit --allow-remote and HTTPS.")


def extract_root_cause(report: str, *, allowed_codes: Sequence[str]) -> str:
    # Do not guess from a mention of the ground-truth label in a long report.
    labels = set(re.findall(r"(?im)^\s*ROOT_CAUSE:\s*([a-z0-9_]+)\s*$", report))
    return next(iter(labels)) if len(labels) == 1 and labels.issubset(allowed_codes) else "unknown"


def evaluation_query(case: dict[str, object], *, allowed_codes: Sequence[str]) -> str:
    alert = object_value(case.get("alert"))
    return (
        f"排查服务 {case['service']} 的告警 {alert.get('alertType', 'unknown')}。"
        f"告警上下文：{json.dumps(alert, ensure_ascii=False)}。"
        "依据工具和知识证据给出根因；证据不足时选 unknown。"
        "报告最后独立一行写 ROOT_CAUSE: <code>，code 只能来自："
        f"{', '.join(allowed_codes)}, unknown。"
    )


def safe_evaluation_trace(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): "[omitted]"
            if str(key).casefold()
            in {
                "authorization",
                "token",
                "accesstoken",
                "password",
                "apikey",
                "secretkey",
                "secretid",
                "arguments",
                "input",
                "output",
                "payload",
                "inputpayload",
            }
            else safe_evaluation_trace(item)
            for key, item in cast(dict[str, object], value).items()
        }
    if isinstance(value, list):
        return [safe_evaluation_trace(item) for item in cast(list[object], value)]
    if isinstance(value, str):
        return re.sub(
            r"(?i)(bearer\s+|(?:api[_-]?key|secret[_-]?key|password|token)\s*[=:]\s*)"
            r"[^\s,;\"']+",
            r"\1[redacted]",
            value,
        )
    return value


class IncidentEvaluationRunner:
    def __init__(self, client: httpx.AsyncClient, settings: EvaluationRunSettings) -> None:
        self._client = client
        self._settings = settings

    async def _request(
        self, method: str, path: str, body: dict[str, object] | None = None
    ) -> dict[str, object]:
        response = await self._client.request(method, path, json=body)
        if response.is_error:
            raise RuntimeError(f"Evaluation API returned HTTP {response.status_code}.")
        envelope = object_value(response.json())
        if envelope.get("ok") is not True:
            raise RuntimeError("Evaluation API returned an unsuccessful envelope.")
        return object_value(envelope.get("data"))

    async def run_case(
        self, case: dict[str, object], *, allowed_codes: Sequence[str]
    ) -> dict[str, object]:
        query = evaluation_query(case, allowed_codes=allowed_codes)
        started = monotonic()
        try:
            report, trace, tool_calls, citations = await asyncio.wait_for(
                self._execute(case, query), timeout=self._settings.timeout_seconds
            )
            status = "completed"
            error_category: str | None = None
        except Exception as exc:
            report, trace, tool_calls, citations = "", {}, [], []
            status = "failed"
            error_category = exc.__class__.__name__
        identity = {"service": case.get("service"), "alert": case.get("alert")}
        return {
            "datasetVersion": case["datasetVersion"],
            "caseId": case["caseId"],
            "expectedRootCause": case["expectedRootCause"],
            "predictedRootCause": extract_root_cause(report, allowed_codes=allowed_codes),
            "latencyMs": round((monotonic() - started) * 1000, 3),
            "agentCalls": None,
            "promptTokens": None,
            "completionTokens": None,
            "costUsd": None,
            "citations": citations,
            "toolCalls": tool_calls,
            "status": status,
            "errorCategory": error_category,
            "runMetadata": {
                "mode": self._settings.mode,
                "modelVersion": self._settings.model_version,
                "configVersion": self._settings.config_version,
                "promptVersion": self._settings.prompt_version,
                "metadataSource": "operator-supplied",
                "inputSha256": hashlib.sha256(
                    json.dumps(identity, sort_keys=True).encode()
                ).hexdigest(),
            },
            "trace": safe_evaluation_trace(trace),
        }

    async def _execute(
        self, case: dict[str, object], query: str
    ) -> tuple[str, dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
        if self._settings.mode == "single-agent":
            return await self._run_chat(query)
        created = await self._request(
            "POST",
            "/aiops/diagnostics",
            {
                "query": query,
                "alert": {**object_value(case.get("alert")), "service": case["service"]},
            },
        )
        task_id = str(created["id"])
        try:
            while True:
                task = await self._request("GET", f"/aiops/diagnostics/{task_id}")
                if task.get("status") in {"succeeded", "failed", "cancelled"}:
                    break
                await asyncio.sleep(self._settings.poll_seconds)
        except asyncio.CancelledError:
            job = created.get("backgroundJob")
            if isinstance(job, dict):
                await self._request(
                    "POST", f"/background-jobs/{cast(dict[str, object], job)['id']}:cancel"
                )
            raise
        if task.get("status") != "succeeded":
            raise RuntimeError("Diagnostic did not complete successfully.")
        trace = await self._request("GET", f"/aiops/diagnostics/{task_id}/evidence-chain")
        reports = objects(trace.get("reports", []))
        report = str(reports[-1].get("content", "")) if reports else ""
        tool_calls = [
            {"id": item.get("id"), "success": item.get("status") == "completed"}
            for item in objects(trace.get("toolCalls", []))
        ]
        # Citation existence is recorded; factual correctness requires independent annotation.
        citations = [
            {"id": item.get("id"), "kind": item.get("kind")}
            for item in objects(trace.get("evidence", []))
        ]
        return report, trace, tool_calls, citations

    async def _run_chat(
        self, query: str
    ) -> tuple[str, dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
        session = await self._request("POST", "/chat/sessions", {"title": "Incident evaluation"})
        session_id = str(session["id"])
        events: list[dict[str, object]] = []
        try:
            async with self._client.stream(
                "POST", f"/chat/sessions/{session_id}/messages:stream", json={"content": query}
            ) as response:
                if response.is_error:
                    raise RuntimeError("Single-Agent stream failed.")
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        event = object_value(json.loads(line[5:]))
                        if event.get("type") == "error":
                            raise RuntimeError("Single-Agent reported a stream error.")
                        events.append(event)
            if not any(event.get("type") == "complete" for event in events):
                raise RuntimeError("Single-Agent stream ended without completion.")
            report = "".join(
                str(event.get("delta", ""))
                for event in events
                if event.get("type") == "content.delta"
            )
            calls = [
                object_value(event["toolCall"])
                for event in events
                if event.get("type") == "tool.call"
            ]
            tool_calls = [
                {"id": call.get("id"), "success": call.get("status") == "completed"}
                for call in calls
                if call.get("status") in {"completed", "failed"}
            ]
            citations = [
                object_value(event["reference"])
                for event in events
                if event.get("type") == "reference.source"
            ]
            return report, {"sessionId": session_id, "events": events}, tool_calls, citations
        finally:
            await self._request("DELETE", f"/chat/sessions/{session_id}")
