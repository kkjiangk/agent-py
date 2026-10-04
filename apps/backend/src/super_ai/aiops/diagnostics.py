"""Evidence-based LangGraph workflow for AIOps diagnostics."""
# pyright: reportMissingTypeStubs=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportTypedDictNotRequiredAccess=false, reportUnnecessaryCast=false

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime, timezone
from operator import add
from time import monotonic
from typing import Annotated, Any, Literal, TypedDict, cast
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from super_ai.aiops.cases import DiagnosisCasePersistor
from super_ai.error_catalog import ERROR_DEFINITIONS
from super_ai.events.checkpoints import WorkflowCheckpointStore
from super_ai.llm import LlmProvider
from super_ai.mcp_client import LocalMcpClient, McpClientError
from super_ai.mcp_connections import McpConnectionService
from super_ai.memory.repositories import (
    DiagnosticReportRecord,
    DiagnosticStepRecord,
    DiagnosticTaskRecord,
    JsonDict,
    MemoryRepositories,
)
from super_ai.observability import elapsed_ms, emit_event
from super_ai.retrieval import (
    KnowledgeRetrievalCitationSource,
    KnowledgeRetrievalError,
    KnowledgeRetrievalHit,
    KnowledgeRetrievalTool,
    KnowledgeRetrievalToolInput,
    KnowledgeRetrievalToolResult,
)
from super_ai.telemetry import get_tracer, record_span_error, safe_span_attributes


class AiopsDiagnosticState(TypedDict, total=False):
    owner_user_id: str
    task_id: str
    query: str
    alert: JsonDict
    accessible_knowledge_base_ids: tuple[str, ...]
    sop_hits: list[JsonDict]
    no_sop_matched: bool
    plan: list[JsonDict]
    plan_origin: str
    plan_index: int
    continue_execution: bool
    execution_failed: bool
    report_id: str
    events: Annotated[list[dict[str, object]], add]
    evidence: Annotated[list[JsonDict], add]
    evidence_ids: Annotated[list[str], add]


logger = logging.getLogger(__name__)

AIOPS_REPORT_TITLE = "告警分析报告"
AIOPS_REPORT_REQUIRED_HEADINGS = (
    "# 告警分析报告",
    "## 📋 活跃告警清单",
    "## 📊 结论",
)


class AiopsDiagnosticService:
    """Run a bounded Plan-Execute-Replan workflow for one owned task."""

    def __init__(
        self,
        *,
        repositories: MemoryRepositories,
        llm_provider: LlmProvider,
        retrieval_tool: KnowledgeRetrievalTool,
        mcp_client: LocalMcpClient | None = None,
        mcp_client_provider: McpConnectionService | None = None,
        cls_region: str,
        cls_topic_id: str,
        case_persistor: DiagnosisCasePersistor | None = None,
        checkpoint_store: WorkflowCheckpointStore | None = None,
    ) -> None:
        self._repositories = repositories
        self._llm_provider = llm_provider
        self._retrieval_tool = retrieval_tool
        self._mcp_client = mcp_client
        self._mcp_client_provider = mcp_client_provider
        if mcp_client is None and mcp_client_provider is None:
            raise ValueError("An MCP client or provider is required.")
        self._cls_region = cls_region
        self._cls_topic_id = cls_topic_id
        self._case_persistor = case_persistor
        self._checkpoint_store = checkpoint_store

    async def stream(
        self,
        *,
        task: DiagnosticTaskRecord,
        accessible_knowledge_base_ids: Sequence[str],
    ) -> AsyncIterator[dict[str, object]]:
        """Execute a diagnostic and yield shared SSE payloads in graph order."""
        started_at = monotonic()
        emit_event(logger, "agent.aiops.started", diagnosticTaskId=task.id)
        await self._repositories.diagnostics.update_task(
            owner_user_id=task.owner_user_id,
            task_id=task.id,
            status="running",
        )
        alert = _json_dict(task.input_payload.get("alert"))
        initial_evidence_ids: list[str] = []
        if alert:
            alert_evidence = await self._repositories.diagnostics.create_evidence(
                owner_user_id=task.owner_user_id,
                evidence_id=f"evidence_{uuid4().hex}",
                task_id=task.id,
                kind="alert",
                source="diagnostic-input",
                summary="Original alert input for the diagnostic.",
                payload=alert,
            )
            initial_evidence_ids.append(alert_evidence.id)
        graph = self._build_graph()
        initial_state: AiopsDiagnosticState = {
            "owner_user_id": task.owner_user_id,
            "task_id": task.id,
            "query": task.query,
            "alert": alert,
            "accessible_knowledge_base_ids": tuple(accessible_knowledge_base_ids),
            "plan_index": 0,
            "execution_failed": False,
            "events": [],
            "evidence": [],
            "evidence_ids": initial_evidence_ids,
        }
        try:
            async for update in graph.astream(initial_state, stream_mode="updates"):
                for node_update in cast(Mapping[str, object], update).values():
                    if not isinstance(node_update, Mapping):
                        continue
                    events = node_update.get("events")
                    if not isinstance(events, list):
                        continue
                    for event in events:
                        if isinstance(event, dict):
                            yield cast(dict[str, object], event)
        except Exception as exc:
            await self._repositories.diagnostics.update_task(
                owner_user_id=task.owner_user_id,
                task_id=task.id,
                status="failed",
                result_payload={
                    "failure": "Diagnostic execution failed before a report was produced."
                },
                completed_at=_now(),
            )
            emit_event(
                logger,
                "agent.aiops.failed",
                diagnosticTaskId=task.id,
                errorCategory=exc.__class__.__name__,
                durationMs=elapsed_ms(started_at),
            )
            yield _error_event("SYSTEM_INTERNAL_ERROR")
            return
        emit_event(
            logger,
            "agent.aiops.completed",
            diagnosticTaskId=task.id,
            durationMs=elapsed_ms(started_at),
        )

    async def _mcp_client_for(self, owner_user_id: str) -> LocalMcpClient:
        if self._mcp_client_provider is not None:
            return await self._mcp_client_provider.client_for_user(owner_user_id=owner_user_id)
        if self._mcp_client is None:
            raise McpClientError("MCP client is unavailable.")
        return self._mcp_client

    def _build_graph(self) -> Any:
        graph = StateGraph(AiopsDiagnosticState)
        graph.add_node("planner", self._planner)
        graph.add_node("executor", self._executor)
        graph.add_node("replanner", self._replanner)
        graph.add_node("report", self._report)
        graph.add_edge(START, "planner")
        graph.add_edge("planner", "executor")
        graph.add_edge("executor", "replanner")
        graph.add_conditional_edges(
            "replanner",
            self._route_after_replanner,
            {"executor": "executor", "report": "report"},
        )
        graph.add_edge("report", END)
        return graph.compile()

    async def _planner(self, state: AiopsDiagnosticState) -> dict[str, object]:
        task_id = str(state["task_id"])
        owner_user_id = str(state["owner_user_id"])
        query = str(state["query"])
        events = [_task_status_event(task_id, "running", "Planner: retrieving SOP evidence.", 15)]
        retrieval_audit_id = f"tool_{uuid4().hex}"
        events.append(
            _tool_event(
                retrieval_audit_id,
                "knowledge_retrieval",
                "started",
                {"query": query},
            )
        )
        await self._create_audit(
            owner_user_id=owner_user_id,
            task_id=task_id,
            audit_id=retrieval_audit_id,
            tool_name="knowledge_retrieval",
            arguments={"query": query},
        )

        retrieval_result: KnowledgeRetrievalToolResult | None = None
        retrieval_error: str | None = None
        try:
            with get_tracer().start_as_current_span(
                "agent.knowledge.retrieve",
                attributes=safe_span_attributes(
                    {"diagnostic.id": task_id, "retrieval.top_k": 3}
                ),
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                try:
                    retrieval_result = await self._retrieval_tool.run(
                        KnowledgeRetrievalToolInput(query=query, top_k=3),
                        owner_user_id=owner_user_id,
                        accessible_knowledge_base_ids=cast(
                            Sequence[str], state["accessible_knowledge_base_ids"]
                        ),
                    )
                except Exception as exc:
                    record_span_error(span, exc)
                    raise
        except KnowledgeRetrievalError as exc:
            retrieval_error = exc.message

        sop_hits: list[JsonDict] = []
        if retrieval_result is not None:
            sop_hits = [_sop_hit_payload(hit) for hit in retrieval_result.results]
            retrieval_payload = {
                "query": retrieval_result.query,
                "results": sop_hits,
                "citations": [
                    _citation_payload(citation) for citation in retrieval_result.citations
                ],
            }
            events.append(
                _tool_event(
                    retrieval_audit_id,
                    "knowledge_retrieval",
                    "completed",
                    retrieval_payload,
                )
            )
            await self._finalize_audit(
                owner_user_id=owner_user_id,
                audit_id=retrieval_audit_id,
                status="completed",
                result_summary=_bounded_json(retrieval_payload),
            )
            events.extend(_reference_event(citation) for citation in retrieval_result.citations)
        else:
            safe_error = retrieval_error or "Knowledge retrieval was unavailable."
            events.extend(
                [
                    _tool_event(
                        retrieval_audit_id,
                        "knowledge_retrieval",
                        "failed",
                        {"error": safe_error},
                    ),
                    _error_event("SYSTEM_UNAVAILABLE"),
                ]
            )
            await self._finalize_audit(
                owner_user_id=owner_user_id,
                audit_id=retrieval_audit_id,
                status="failed",
                error_message=safe_error,
            )

        no_sop_matched = not sop_hits
        if no_sop_matched:
            events.append(
                _task_status_event(
                    task_id,
                    "running",
                    "Planner: no SOP matched; using a generic evidence-gathering plan.",
                    25,
                )
            )

        try:
            mcp_client = await self._mcp_client_for(owner_user_id)
            discovered_tools = await mcp_client.discover_tools()
            available_tools = [definition.name for definition in discovered_tools]
        except McpClientError:
            available_tools = []
            events.append(
                _task_status_event(
                    task_id,
                    "running",
                    "Planner: MCP discovery was unavailable; execution will report an "
                    "explicit failure.",
                    30,
                )
            )

        plan, plan_origin = await self._create_plan(
            query=query,
            alert=_json_dict(state.get("alert")),
            sop_hits=sop_hits,
            no_sop_matched=no_sop_matched,
            available_tools=available_tools,
        )
        events.append(
            _task_status_event(
                task_id,
                "running",
                f"Planner: created a {plan_origin} plan with {len(plan)} step(s).",
                35,
            )
        )
        planner_payload: JsonDict = {
            "noSopMatched": no_sop_matched,
            "sopHits": sop_hits,
            "plan": plan,
            "planOrigin": plan_origin,
            "retrievalError": retrieval_error,
        }
        planner_step = await self._create_step(
            owner_user_id=owner_user_id,
            task_id=task_id,
            phase="planner",
            status="completed",
            payload=planner_payload,
        )
        persisted_evidence_ids: list[str] = []
        if retrieval_result is not None:
            for citation in retrieval_result.citations:
                citation_payload = _citation_payload(citation)
                evidence_record = await self._repositories.diagnostics.create_evidence(
                    owner_user_id=owner_user_id,
                    evidence_id=f"evidence_{uuid4().hex}",
                    task_id=task_id,
                    step_id=planner_step.id,
                    kind="knowledge_reference",
                    source=str(citation_payload["source"]),
                    summary=str(citation_payload["title"]),
                    payload=citation_payload,
                )
                persisted_evidence_ids.append(evidence_record.id)
        elif retrieval_error is not None:
            evidence_record = await self._repositories.diagnostics.create_evidence(
                owner_user_id=owner_user_id,
                evidence_id=f"evidence_{uuid4().hex}",
                task_id=task_id,
                step_id=planner_step.id,
                kind="knowledge_reference",
                source="knowledge_retrieval",
                summary=retrieval_error,
                payload={"error": retrieval_error},
            )
            persisted_evidence_ids.append(evidence_record.id)
        await self._save_checkpoint(
            state,
            "planner",
            planner_payload,
        )
        return {
            "sop_hits": sop_hits,
            "no_sop_matched": no_sop_matched,
            "plan": plan,
            "plan_origin": plan_origin,
            "evidence_ids": persisted_evidence_ids,
            "events": events,
        }

    async def _executor(self, state: AiopsDiagnosticState) -> dict[str, object]:
        task_id = str(state["task_id"])
        owner_user_id = str(state["owner_user_id"])
        plan = cast(list[JsonDict], state.get("plan") or [])
        plan_index = int(state.get("plan_index") or 0)
        if plan_index >= len(plan):
            return {"events": []}

        step = plan[plan_index]
        tool_name = str(step.get("tool") or "")
        arguments = _json_dict(step.get("arguments"))
        audit_id = f"tool_{uuid4().hex}"
        events = [
            _task_status_event(
                task_id,
                "running",
                f"Executor: running step {plan_index + 1} with {tool_name}.",
                45 + min(plan_index * 15, 30),
            ),
            _tool_event(audit_id, tool_name, "started", arguments),
        ]
        await self._create_audit(
            owner_user_id=owner_user_id,
            task_id=task_id,
            audit_id=audit_id,
            tool_name=tool_name,
            arguments=arguments,
        )

        try:
            if tool_name == "knowledge_retrieval":
                with get_tracer().start_as_current_span(
                    "agent.knowledge.retrieve",
                    attributes=safe_span_attributes(
                        {"diagnostic.id": task_id, "tool.name": tool_name}
                    ),
                    record_exception=False,
                    set_status_on_exception=False,
                ) as span:
                    try:
                        result = await self._retrieval_tool.run(
                            KnowledgeRetrievalToolInput(
                                query=str(arguments.get("query") or state["query"]),
                                top_k=_optional_int(arguments.get("topK")),
                            ),
                            owner_user_id=owner_user_id,
                            accessible_knowledge_base_ids=cast(
                                Sequence[str], state["accessible_knowledge_base_ids"]
                            ),
                        )
                    except Exception as exc:
                        record_span_error(span, exc)
                        raise
                output: object = {
                    "results": [_sop_hit_payload(hit) for hit in result.results],
                    "citations": [_citation_payload(citation) for citation in result.citations],
                }
            elif tool_name:
                mcp_client = await self._mcp_client_for(owner_user_id)
                with get_tracer().start_as_current_span(
                    "agent.mcp.tool.call",
                    attributes=safe_span_attributes(
                        {"diagnostic.id": task_id, "tool.name": tool_name}
                    ),
                    record_exception=False,
                    set_status_on_exception=False,
                ) as span:
                    try:
                        output = await mcp_client.call_tool(tool_name, arguments)
                    except Exception as exc:
                        record_span_error(span, exc)
                        raise
            else:
                raise ValueError("Diagnostic plan did not specify a tool.")
        except Exception as exc:
            safe_error = _safe_error(exc)
            evidence: JsonDict = {
                "stepId": str(step.get("id") or f"step_{plan_index + 1}"),
                "tool": tool_name or "unknown",
                "status": "failed",
                "summary": safe_error,
            }
            events.extend(
                [
                    _tool_event(audit_id, tool_name or "unknown", "failed", {"error": safe_error}),
                    _error_event("SYSTEM_UNAVAILABLE"),
                ]
            )
            await self._finalize_audit(
                owner_user_id=owner_user_id,
                audit_id=audit_id,
                status="failed",
                error_message=safe_error,
            )
            executor_step = await self._create_step(
                owner_user_id=owner_user_id,
                task_id=task_id,
                phase="executor",
                status="failed",
                payload={"planStep": step, "tool": tool_name, "error": safe_error},
            )
            evidence_record = await self._repositories.diagnostics.create_evidence(
                owner_user_id=owner_user_id,
                evidence_id=f"evidence_{uuid4().hex}",
                task_id=task_id,
                step_id=executor_step.id,
                tool_call_id=audit_id,
                kind=_evidence_kind_for_tool(tool_name),
                source=tool_name or "unknown",
                summary=safe_error,
                payload={"error": safe_error, "arguments": arguments},
            )
            evidence["evidenceId"] = evidence_record.id
            await self._save_checkpoint(state, "executor", {"evidence": evidence})
            return {
                "plan_index": plan_index + 1,
                "execution_failed": True,
                "evidence": [evidence],
                "evidence_ids": [evidence_record.id],
                "events": events,
            }

        summary = _tool_result_summary(tool_name, output)
        evidence: JsonDict = {
            "stepId": str(step.get("id") or f"step_{plan_index + 1}"),
            "tool": tool_name,
            "status": "completed",
            "summary": summary,
        }
        events.append(_tool_event(audit_id, tool_name, "completed", _safe_value(output)))
        if tool_name == "knowledge_retrieval" and isinstance(output, Mapping):
            citations = output.get("citations")
            if isinstance(citations, list):
                events.extend(_reference_event_from_payload(citation) for citation in citations)
        else:
            events.append(
                _sse_event(
                    "reference.source",
                    {
                        "reference": {
                            "id": audit_id,
                            "title": f"{tool_name} result",
                            "sourceType": "log",
                            "metadata": {"stepId": evidence["stepId"], "tool": tool_name},
                        }
                    },
                )
            )
        await self._finalize_audit(
            owner_user_id=owner_user_id,
            audit_id=audit_id,
            status="completed",
            result_summary=summary,
        )
        executor_step = await self._create_step(
            owner_user_id=owner_user_id,
            task_id=task_id,
            phase="executor",
            status="completed",
            payload={"planStep": step, "tool": tool_name, "output": _safe_value(output)},
        )
        evidence_record = await self._repositories.diagnostics.create_evidence(
            owner_user_id=owner_user_id,
            evidence_id=f"evidence_{uuid4().hex}",
            task_id=task_id,
            step_id=executor_step.id,
            tool_call_id=audit_id,
            kind=_evidence_kind_for_tool(tool_name),
            source=tool_name,
            summary=summary,
            payload={"arguments": arguments, "output": _safe_value(output)},
        )
        evidence["evidenceId"] = evidence_record.id
        await self._save_checkpoint(state, "executor", {"evidence": evidence})
        return {
            "plan_index": plan_index + 1,
            "evidence": [evidence],
            "evidence_ids": [evidence_record.id],
            "events": events,
        }

    async def _replanner(self, state: AiopsDiagnosticState) -> dict[str, object]:
        task_id = str(state["task_id"])
        plan = cast(list[JsonDict], state.get("plan") or [])
        plan_index = int(state.get("plan_index") or 0)
        execution_failed = bool(state.get("execution_failed"))
        continue_execution = plan_index < len(plan) and not execution_failed
        decision = (
            "continuing with the next bounded step" if continue_execution else "moving to Report"
        )
        events = [
            _task_status_event(
                task_id,
                "running",
                f"Replanner: {decision} based on recorded execution evidence.",
                70 if continue_execution else 80,
            )
        ]
        await self._create_step(
            owner_user_id=str(state["owner_user_id"]),
            task_id=task_id,
            phase="replanner",
            status="completed",
            payload={
                "planIndex": plan_index,
                "planLength": len(plan),
                "executionFailed": execution_failed,
                "decision": "executor" if continue_execution else "report",
            },
        )
        await self._save_checkpoint(
            state,
            "replanner",
            {
                "planIndex": plan_index,
                "planLength": len(plan),
                "executionFailed": execution_failed,
                "decision": "executor" if continue_execution else "report",
            },
        )
        return {"continue_execution": continue_execution, "events": events}

    async def _report(self, state: AiopsDiagnosticState) -> dict[str, object]:
        task_id = str(state["task_id"])
        owner_user_id = str(state["owner_user_id"])
        evidence = cast(list[JsonDict], state.get("evidence") or [])
        evidence_ids = _unique_strings(cast(list[str], state.get("evidence_ids") or []))
        no_sop_matched = bool(state.get("no_sop_matched"))
        status: Literal["succeeded", "failed"] = (
            "failed" if bool(state.get("execution_failed")) else "succeeded"
        )
        events = [
            _task_status_event(task_id, "running", "Report: compiling evidence-backed report.", 90)
        ]
        report_content, report_generation = await self._generate_report_content(state)
        report_payload: JsonDict = {
            "noSopMatched": no_sop_matched,
            "plan": _json_list(state.get("plan")),
            "planOrigin": str(state.get("plan_origin") or "generic"),
            "evidence": evidence,
            "evidenceIds": evidence_ids,
            "reportGeneration": report_generation,
            "status": status,
        }
        await self._create_step(
            owner_user_id=owner_user_id,
            task_id=task_id,
            phase="report",
            status="completed",
            payload={"status": status, "evidenceIds": evidence_ids},
        )
        report = await self._repositories.diagnostics.add_report(
            owner_user_id=owner_user_id,
            report_id=f"report_{uuid4().hex}",
            task_id=task_id,
            title=AIOPS_REPORT_TITLE,
            content=report_content,
            payload=report_payload,
        )
        for evidence_id in evidence_ids:
            await self._repositories.diagnostics.link_report_evidence(
                owner_user_id=owner_user_id,
                link_id=f"report_evidence_{uuid4().hex}",
                task_id=task_id,
                report_id=report.id,
                evidence_id=evidence_id,
            )
        result_payload: JsonDict = {**report_payload, "reportId": report.id}
        updated_task = await self._repositories.diagnostics.update_task(
            owner_user_id=owner_user_id,
            task_id=task_id,
            status=status,
            result_payload=result_payload,
            completed_at=_now(),
        )
        if updated_task is None:
            raise RuntimeError("Diagnostic task disappeared during report persistence.")
        if status == "succeeded" and self._case_persistor is not None:
            case = await self._case_persistor.persist(task=updated_task, report=report)
            refreshed_task = await self._repositories.diagnostics.update_task(
                owner_user_id=owner_user_id,
                task_id=task_id,
                status=status,
                result_payload={**result_payload, "diagnosticCaseId": case.id},
                completed_at=_now(),
            )
            if refreshed_task is not None:
                updated_task = refreshed_task
        await self._save_checkpoint(
            state,
            "report",
            {"reportId": report.id, "status": status, "resultPayload": result_payload},
        )
        events.extend(
            [
                _sse_event(
                    "report",
                    {
                        "report": {
                            "id": report.id,
                            "title": report.title,
                            "content": report.content,
                            "format": "markdown",
                        }
                    },
                ),
                _task_status_event(task_id, status, "Report: diagnostic finished.", 100),
                _sse_event(
                    "complete",
                    {
                        "result": {
                            "task": _task_payload(updated_task),
                            "report": _report_payload(report),
                        }
                    },
                ),
            ]
        )
        return {"report_id": report.id, "events": events}

    async def _generate_report_content(self, state: AiopsDiagnosticState) -> tuple[str, str]:
        fallback = _fallback_report_content(
            alert=_json_dict(state.get("alert")),
            no_sop_matched=bool(state.get("no_sop_matched")),
            sop_hits=cast(list[JsonDict], state.get("sop_hits") or []),
            evidence=cast(list[JsonDict], state.get("evidence") or []),
            execution_failed=bool(state.get("execution_failed")),
        )
        prompt = _report_prompt(state)
        try:
            with get_tracer().start_as_current_span(
                "agent.llm.report",
                attributes=safe_span_attributes(
                    {"diagnostic.id": str(state.get("task_id") or "unknown")}
                ),
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                try:
                    response = await self._llm_provider.create_chat_model().ainvoke(prompt)
                except Exception as exc:
                    record_span_error(span, exc)
                    raise
        except Exception:
            return fallback, "fallback"
        report = _clean_markdown_report(_model_text(response))
        return (report, "llm") if report is not None else (fallback, "fallback")

    def _route_after_replanner(self, state: AiopsDiagnosticState) -> str:
        return "executor" if state.get("continue_execution") else "report"

    async def _create_plan(
        self,
        *,
        query: str,
        alert: JsonDict,
        sop_hits: Sequence[JsonDict],
        no_sop_matched: bool,
        available_tools: Sequence[str],
    ) -> tuple[list[JsonDict], str]:
        generic_plan = [self._generic_search_log_step(query)]
        prompt = (
            "Return JSON only with a `steps` array. Each step has `id`, `tool`, `arguments`, and "
            "`purpose`. Plan a bounded AIOps investigation using only these tools: "
            f"{json.dumps(list(available_tools))}. User query: {query}. Alert: "
            f"{json.dumps(alert)}. SOP evidence: {json.dumps(list(sop_hits))}. "
            f"No SOP matched: {str(no_sop_matched).lower()}. Prefer SearchLog for CLS evidence."
        )
        try:
            with get_tracer().start_as_current_span(
                "agent.llm.plan",
                attributes=safe_span_attributes(
                    {"agent.available_tool_count": len(available_tools)}
                ),
                record_exception=False,
                set_status_on_exception=False,
            ) as span:
                try:
                    response = await self._llm_provider.create_chat_model().ainvoke(prompt)
                except Exception as exc:
                    record_span_error(span, exc)
                    raise
            plan = _validated_plan(_model_text(response), available_tools)
        except Exception:
            plan = []
        search_log_steps = [step for step in plan if step.get("tool") == "SearchLog"]
        if not search_log_steps:
            return generic_plan, "generic"
        return [self._normalized_search_log_step(search_log_steps[0], query)], (
            "SOP-backed" if sop_hits else "generic"
        )

    def _generic_search_log_step(self, query: str) -> JsonDict:
        now_ms = int(_now().timestamp() * 1000)
        return {
            "id": "search-cls-logs",
            "tool": "SearchLog",
            "arguments": {
                "Region": self._cls_region,
                "TopicId": self._cls_topic_id,
                "From": now_ms - 86_400_000,
                "To": now_ms,
                "Query": "*",
                "Limit": 20,
            },
            "purpose": f"Gather real CLS evidence relevant to: {query}",
        }

    def _normalized_search_log_step(self, step: JsonDict, query: str) -> JsonDict:
        """Keep model planning bounded to an executable real CLS search step."""
        generic_step = self._generic_search_log_step(query)
        model_arguments = _json_dict(step.get("arguments"))
        limit_value = model_arguments.get("Limit")
        arguments = _json_dict(generic_step["arguments"])
        if isinstance(limit_value, int) and 1 <= limit_value <= 100:
            arguments["Limit"] = limit_value
        return {
            "id": str(step.get("id") or generic_step["id"]),
            "tool": "SearchLog",
            "arguments": arguments,
            "purpose": str(step.get("purpose") or generic_step["purpose"]),
        }

    async def _create_step(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        phase: str,
        status: str,
        payload: JsonDict,
    ) -> DiagnosticStepRecord:
        existing_steps = await self._repositories.diagnostics.list_steps(
            owner_user_id=owner_user_id,
            task_id=task_id,
        )
        return await self._repositories.diagnostics.create_step(
            owner_user_id=owner_user_id,
            step_id=f"diagnostic_step_{uuid4().hex}",
            task_id=task_id,
            sequence=len(existing_steps) + 1,
            phase=phase,
            status=status,
            payload=payload,
        )

    async def _create_audit(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        audit_id: str,
        tool_name: str,
        arguments: JsonDict,
    ) -> None:
        repository = self._repositories.tool_call_audits
        if repository is not None:
            await repository.create_for_diagnostic_task(
                owner_user_id=owner_user_id,
                audit_id=audit_id,
                diagnostic_task_id=task_id,
                tool_name=tool_name,
                arguments=arguments,
            )

    async def _finalize_audit(
        self,
        *,
        owner_user_id: str,
        audit_id: str,
        status: str,
        result_summary: str | None = None,
        error_message: str | None = None,
    ) -> None:
        repository = self._repositories.tool_call_audits
        if repository is not None:
            await repository.finalize(
                owner_user_id=owner_user_id,
                audit_id=audit_id,
                status=status,
                result_summary=result_summary,
                error_message=error_message,
            )

    async def _save_checkpoint(
        self,
        state: AiopsDiagnosticState,
        node: str,
        payload: JsonDict,
    ) -> None:
        task_id = str(state["task_id"])
        await self._repositories.diagnostics.save_checkpoint(
            owner_user_id=str(state["owner_user_id"]),
            checkpoint_record_id=f"checkpoint_{uuid4().hex}",
            task_id=task_id,
            thread_id=f"aiops:{task_id}",
            checkpoint_ns=node,
            checkpoint_id=f"{node}_{uuid4().hex}",
            checkpoint_payload=payload,
            metadata={"node": node},
        )
        if self._checkpoint_store is not None:
            await self._checkpoint_store.save(
                owner_user_id=str(state["owner_user_id"]),
                task_id=task_id,
                node=node,
                payload=payload,
            )


def _validated_plan(text: str, available_tools: Sequence[str]) -> list[JsonDict]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match is None:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, Mapping):
        return []
    raw_steps = parsed.get("steps")
    if not isinstance(raw_steps, list):
        return []
    allowed_tools = set(available_tools) | {"knowledge_retrieval"}
    steps: list[JsonDict] = []
    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, Mapping):
            continue
        tool_name = raw_step.get("tool")
        arguments = raw_step.get("arguments")
        if not isinstance(tool_name, str) or tool_name not in allowed_tools:
            continue
        if not isinstance(arguments, Mapping):
            continue
        steps.append(
            {
                "id": str(raw_step.get("id") or f"step_{index + 1}"),
                "tool": tool_name,
                "arguments": _json_dict(arguments),
                "purpose": str(raw_step.get("purpose") or "Collect diagnostic evidence."),
            }
        )
    return steps


def _model_text(response: object) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(item.get("text", "")) if isinstance(item, Mapping) else str(item)
            for item in content
        )
    return str(content)


def _sop_hit_payload(hit: KnowledgeRetrievalHit) -> JsonDict:
    return {
        "chunkId": hit.chunk_id,
        "documentId": hit.document_id,
        "knowledgeBaseId": hit.knowledge_base_id,
        "content": hit.content,
        "source": hit.source,
        "metadata": _json_dict(hit.metadata),
        "score": hit.score,
        "vectorRank": hit.vector_rank,
        "bm25Rank": hit.bm25_rank,
        "rerankRank": hit.rerank_rank,
        "vectorScore": hit.vector_score,
        "bm25Score": hit.bm25_score,
        "rrfScore": hit.rrf_score,
        "rerankScore": hit.rerank_score,
    }


def _citation_payload(citation: KnowledgeRetrievalCitationSource) -> JsonDict:
    return {
        "id": citation.id,
        "title": citation.title,
        "sourceType": citation.source_type,
        "chunkId": citation.chunk_id,
        "documentId": citation.document_id,
        "knowledgeBaseId": citation.knowledge_base_id,
        "source": citation.source,
        "metadata": _json_dict(citation.metadata),
        "score": citation.score,
        "vectorRank": citation.vector_rank,
        "bm25Rank": citation.bm25_rank,
        "rerankRank": citation.rerank_rank,
        "vectorScore": citation.vector_score,
        "bm25Score": citation.bm25_score,
        "rrfScore": citation.rrf_score,
        "rerankScore": citation.rerank_score,
    }


def _reference_event(citation: KnowledgeRetrievalCitationSource) -> dict[str, object]:
    return _sse_event("reference.source", {"reference": _citation_payload(citation)})


def _reference_event_from_payload(citation: object) -> dict[str, object]:
    return _sse_event("reference.source", {"reference": _json_dict(citation)})


def _tool_event(
    audit_id: str,
    name: str,
    status: Literal["started", "completed", "failed"],
    payload: object,
) -> dict[str, object]:
    key = "input" if status == "started" else "output"
    return _sse_event(
        "tool.call",
        {"toolCall": {"id": audit_id, "name": name, "status": status, key: _safe_value(payload)}},
    )


def _task_status_event(
    task_id: str,
    status: Literal["running", "succeeded", "failed"],
    message: str,
    progress: int,
) -> dict[str, object]:
    return _sse_event(
        "task.status",
        {"task": {"id": task_id, "status": status, "message": message, "progress": progress}},
    )


def _error_event(code: str) -> dict[str, object]:
    category, http_status, message = ERROR_DEFINITIONS[code]
    return _sse_event(
        "error",
        {
            "error": {
                "code": code,
                "category": category,
                "httpStatus": http_status,
                "message": message,
            }
        },
    )


def _sse_event(event_type: str, payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": f"evt_{uuid4().hex}",
        "type": event_type,
        "channel": "aiops",
        "timestamp": _now().isoformat(),
        **payload,
    }


def _task_payload(record: DiagnosticTaskRecord) -> JsonDict:
    return {
        "id": record.id,
        "ownerUserId": record.owner_user_id,
        "status": record.status,
        "query": record.query,
        "inputPayload": record.input_payload,
        "resultPayload": record.result_payload,
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
        "completedAt": record.completed_at.isoformat() if record.completed_at is not None else None,
    }


def _report_payload(report: DiagnosticReportRecord) -> JsonDict:
    return {
        "id": report.id,
        "title": report.title,
        "content": report.content,
        "payload": _json_dict(report.payload),
        "createdAt": report.created_at.isoformat(),
    }


def _report_prompt(state: AiopsDiagnosticState) -> str:
    report_context = {
        "diagnosticQuery": str(state.get("query") or ""),
        "alert": _json_dict(state.get("alert")),
        "noSopMatched": bool(state.get("no_sop_matched")),
        "sopEvidence": _report_sop_context(state.get("sop_hits")),
        "plan": _json_list(state.get("plan")),
        "executionFailed": bool(state.get("execution_failed")),
        "executionEvidence": _report_evidence_context(state.get("evidence")),
    }
    context_json = json.dumps(
        _safe_value(report_context),
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )[:12_000]
    return f"""你是一个严谨的 AIOps 诊断报告生成器。请只根据下方“诊断事实”生成最终报告。

输出要求：
- 最终输出必须是纯 Markdown 文本，不要输出 JSON，不要使用包裹全文的 Markdown 代码围栏。
- 所有告警、时间、服务、症状、日志、根因、排查步骤和建议必须来自诊断事实；严禁编造。
- 缺失字段写“未获取”，证据不能支持根因时写“证据不足，无法确认根因”。
- 工具调用失败必须在“日志证据”“已执行的排查步骤”和“结论”中如实说明，不得跳过。
- 没有匹配 SOP 时，必须在处理建议和结论中说明使用了通用诊断计划。
- 有多个告警时，按相同结构依次生成“告警根因分析2”“处理方案执行2”等章节。
- 必须严格保留下面的一级、二级和三级标题结构。

# 告警分析报告

---

## 📋 活跃告警清单

| 告警名称 | 级别 | 目标服务 | 首次触发时间 | 最新触发时间 | 状态 |
|---------|------|----------|-------------|-------------|------|
| [名称] | [级别] | [服务] | [首次时间] | [最新时间] | [状态] |

---

## 🔍 告警根因分析1 - [告警名称]

### 告警详情
- **告警级别**: [级别]
- **受影响服务**: [服务名]
- **持续时间**: [有证据时填写，否则未获取]

### 症状描述
[仅描述证据中存在的症状]

### 日志证据
[引用真实工具返回的关键日志，失败或无结果时明确说明]

### 根因结论
[基于证据得出；证据不足时明确无法确认]

---

## 🛠️ 处理方案执行1 - [告警名称]

### 已执行的排查步骤
1. [仅列出真实执行过的步骤]

### 处理建议
[基于 SOP 或证据给出；没有 SOP 时标注通用建议]

### 预期效果
[说明建议实施后的预期效果，不得写成已执行结果]

---

## 📊 结论

### 整体评估
[总结已验证事实和无法验证的部分]

### 关键发现
- [证据支持的发现]

### 后续建议
1. [可执行建议]

### 风险评估
[仅根据告警级别、持续时间和影响证据评估；信息不足时明确说明]

诊断事实：
{context_json}
"""


def _clean_markdown_report(content: str) -> str | None:
    report = content.strip()
    fenced = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*)\n```", report, flags=re.DOTALL)
    if fenced is not None:
        report = fenced.group(1).strip()
    if report.startswith(("{", "[")):
        return None
    if not all(heading in report for heading in AIOPS_REPORT_REQUIRED_HEADINGS):
        return None
    return report


def _fallback_report_content(
    *,
    alert: JsonDict,
    no_sop_matched: bool,
    sop_hits: Sequence[JsonDict],
    evidence: Sequence[JsonDict],
    execution_failed: bool,
) -> str:
    alert_name = _report_value(alert, "alertName", "name")
    severity = _report_value(alert, "severity", "level")
    service = _report_value(alert, "service", "target")
    starts_at = _report_value(alert, "startsAt", "startTime")
    latest_at = _report_value(alert, "updatedAt", "endsAt", "latestTime")
    status = _report_value(alert, "status")
    evidence_lines = _fallback_evidence_lines(evidence)
    sop_line = (
        "未检索到匹配的 SOP，本报告采用通用诊断计划。"
        if no_sop_matched
        else "已检索到 SOP：" + "、".join(str(hit.get("source", "未获取")) for hit in sop_hits)
    )
    execution_line = (
        "诊断工具执行失败，部分结论无法验证。" if execution_failed else "诊断流程已执行完成。"
    )
    first_suggestion = (
        "1. 检查失败的工具调用并恢复数据源连接。"
        if execution_failed
        else "1. 继续补充相关服务的指标和日志证据。"
    )
    lines = [
        "# 告警分析报告",
        "",
        "---",
        "",
        "## 📋 活跃告警清单",
        "",
        "| 告警名称 | 级别 | 目标服务 | 首次触发时间 | 最新触发时间 | 状态 |",
        "|---------|------|----------|-------------|-------------|------|",
        f"| {alert_name} | {severity} | {service} | {starts_at} | {latest_at} | {status} |",
        "",
        "---",
        "",
        f"## 🔍 告警根因分析1 - {alert_name}",
        "",
        "### 告警详情",
        f"- **告警级别**: {severity}",
        f"- **受影响服务**: {service}",
        "- **持续时间**: 未获取",
        "",
        "### 症状描述",
        "当前仅能确认诊断输入和下列工具执行结果，未获取可独立验证的完整症状指标。",
        "",
        "### 日志证据",
        *evidence_lines,
        "",
        "### 根因结论",
        "证据不足，无法确认根因。",
        "",
        "---",
        "",
        f"## 🛠️ 处理方案执行1 - {alert_name}",
        "",
        "### 已执行的排查步骤",
        *[f"{index}. {line.removeprefix('- ')}" for index, line in enumerate(evidence_lines, 1)],
        "",
        "### 处理建议",
        sop_line,
        "在变更系统状态前，请补充可验证的日志和指标证据，并由值班人员确认处置动作。",
        "",
        "### 预期效果",
        "补充证据后可缩小故障范围，并验证后续处置是否降低告警影响；当前尚未执行处置动作。",
        "",
        "---",
        "",
        "## 📊 结论",
        "",
        "### 整体评估",
        execution_line,
        "当前报告未获得足以确认根因的完整证据，不作未经验证的根因判断。",
        "",
        "### 关键发现",
        f"- {sop_line}",
        f"- {execution_line}",
        "",
        "### 后续建议",
        first_suggestion,
        "2. 将新增证据与告警触发时间对齐后重新执行诊断。",
        "",
        "### 风险评估",
        f"告警级别为 {severity}；由于影响范围和持续时间信息不完整，当前风险等级无法进一步确认。",
    ]
    return "\n".join(lines)


def _report_value(payload: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().replace("|", "\\|")
    return "未获取"


def _fallback_evidence_lines(evidence: Sequence[JsonDict]) -> list[str]:
    if not evidence:
        return ["- 未获取工具证据，无法验证日志症状。"]
    lines: list[str] = []
    for item in evidence:
        tool = str(item.get("tool") or "未知工具")
        status = str(item.get("status") or "unknown")
        details = _evidence_detail_lines(item)
        lines.append(f"- {tool} [{status}]：{details[0].removeprefix('  - ')}")
    return lines


def _evidence_detail_lines(evidence: JsonDict) -> list[str]:
    summary = evidence.get("summary")
    if not isinstance(summary, str):
        return ["  - No serializable evidence summary was returned."]
    try:
        tool_content = json.loads(summary)
        if isinstance(tool_content, Mapping) and isinstance(tool_content.get("records"), list):
            return _search_log_detail_lines(cast(list[object], tool_content["records"]))
        first_item = tool_content[0] if isinstance(tool_content, list) and tool_content else None
        raw_logs = first_item.get("text") if isinstance(first_item, Mapping) else None
        logs = json.loads(raw_logs) if isinstance(raw_logs, str) else None
    except (IndexError, TypeError, json.JSONDecodeError):
        return [f"  - {summary}"]
    if not isinstance(logs, list):
        return [f"  - {summary}"]
    if not logs:
        return ["  - The real tool returned no matching records."]
    lines: list[str] = []
    for log in logs[:10]:
        if not isinstance(log, Mapping):
            continue
        raw_log_json = log.get("LogJson")
        try:
            log_payload = json.loads(raw_log_json) if isinstance(raw_log_json, str) else {}
        except json.JSONDecodeError:
            log_payload = {}
        if not isinstance(log_payload, Mapping):
            continue
        scenario = log_payload.get("scenario", "unknown")
        service = log_payload.get("service", "unknown")
        message = log_payload.get("message", "")
        lines.append(f"  - scenario={scenario}; service={service}; message={message}")
    return lines or [f"  - {summary}"]


def _tool_result_summary(tool_name: str, output: object) -> str:
    if tool_name != "SearchLog":
        return _bounded_json(output)
    records = _search_log_records(output)
    if not records:
        return json.dumps(
            {"recordCount": 0, "records": [], "message": "CLS 未返回可解析日志。"},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return json.dumps(
        {"recordCount": len(records), "records": records[:10]},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _search_log_records(output: object) -> list[JsonDict]:
    if not isinstance(output, Sequence) or isinstance(output, str | bytes):
        return []
    records: list[JsonDict] = []
    for item in output:
        if not isinstance(item, Mapping):
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        try:
            logs = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(logs, list):
            continue
        for log in logs:
            if not isinstance(log, Mapping):
                continue
            raw_payload = log.get("LogJson")
            try:
                payload = json.loads(raw_payload) if isinstance(raw_payload, str) else {}
            except json.JSONDecodeError:
                payload = {}
            if not isinstance(payload, Mapping):
                continue
            records.append(
                {
                    key: _safe_value(payload[key])
                    for key in (
                        "timestamp",
                        "level",
                        "service",
                        "host",
                        "event",
                        "message",
                        "latency_ms",
                        "exception",
                        "request_id",
                    )
                    if key in payload
                }
            )
    return records


def _search_log_detail_lines(records: Sequence[object]) -> list[str]:
    lines: list[str] = []
    for record in records[:10]:
        if not isinstance(record, Mapping):
            continue
        fields = [
            f"{key}={record[key]}"
            for key in ("timestamp", "level", "service", "event", "message", "latency_ms")
            if key in record
        ]
        if fields:
            lines.append("  - " + "; ".join(fields))
    return lines or ["  - CLS 未返回可解析日志。"]


def _report_sop_context(value: object) -> list[JsonDict]:
    return [
        {
            "source": str(hit.get("source") or "未获取"),
            "score": hit.get("score"),
            "content": str(hit.get("content") or "")[:1_200],
        }
        for hit in _json_list(value)[:3]
    ]


def _report_evidence_context(value: object) -> list[JsonDict]:
    return [
        {
            "tool": str(item.get("tool") or "未知工具"),
            "status": str(item.get("status") or "unknown"),
            "summary": str(item.get("summary") or "")[:4_000],
        }
        for item in _json_list(value)
    ]


def _safe_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_safe_value(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def _bounded_json(value: object, limit: int = 4_000) -> str:
    encoded = json.dumps(_safe_value(value), ensure_ascii=True, separators=(",", ":"), default=str)
    return encoded[:limit]


def _safe_error(exc: Exception) -> str:
    message = re.sub(r"(?:sk-[A-Za-z0-9_-]+|AKID[A-Za-z0-9]+)", "[redacted]", str(exc))
    return message[:500] or "Tool invocation failed."


def _evidence_kind_for_tool(tool_name: str) -> str:
    if tool_name == "knowledge_retrieval":
        return "knowledge_reference"
    return "log"


def _unique_strings(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _json_dict(value: object) -> JsonDict:
    safe_value = _safe_value(value)
    return cast(JsonDict, safe_value) if isinstance(safe_value, dict) else {}


def _json_list(value: object) -> list[JsonDict]:
    if not isinstance(value, list):
        return []
    return [_json_dict(item) for item in value]


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _now() -> datetime:
    return datetime.now(timezone.utc)
