"""Streaming RAG chat service and LangChain Agent adapter."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import import_module
from time import monotonic
from typing import Any, Literal, Protocol, TypedDict, cast
from uuid import uuid4

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from super_ai.chat.configuration import (
    DEFAULT_CHAT_PROMPT_CONTENT,
    DEFAULT_CHAT_PROMPT_LABEL,
    SelectedChatSkill,
    build_chat_system_prompt,
)
from super_ai.chat.memory import ChatContextLimitReached, ChatMemoryService, memory_payload
from super_ai.error_catalog import ERROR_DEFINITIONS
from super_ai.llm import LlmProvider
from super_ai.mcp_client import LocalMcpClient, create_current_time_tool
from super_ai.mcp_connections import McpConnectionService
from super_ai.memory.repositories import (
    ChatMessageRecord,
    ChatSessionRecord,
    JsonDict,
    MemoryRepositories,
)
from super_ai.observability import elapsed_ms, emit_event
from super_ai.retrieval import (
    KnowledgeRetrievalTool,
    create_langchain_knowledge_retrieval_tool,
)

ToolCallStatus = Literal["started", "delta", "completed", "failed"]
logger = logging.getLogger(__name__)


class SsePayload(TypedDict):
    id: str
    type: str
    channel: Literal["chat"]
    timestamp: str


@dataclass(frozen=True, slots=True)
class ChatAgentContentDelta:
    """A final-answer text delta emitted by the Agent."""

    delta: str


@dataclass(frozen=True, slots=True)
class ChatAgentReasoningDelta:
    """Model-provided reasoning delta, never synthesized by the service."""

    delta: str


@dataclass(frozen=True, slots=True)
class ChatAgentToolCall:
    """A tool lifecycle event emitted by the Agent."""

    id: str
    name: str
    status: ToolCallStatus
    input: object | None = None
    output: object | None = None


@dataclass(frozen=True, slots=True)
class ChatAgentReference:
    """A citation/reference emitted from a tool result."""

    id: str
    title: str
    source_type: str
    chunk_id: str | None = None
    document_id: str | None = None
    knowledge_base_id: str | None = None
    source: str | None = None
    uri: str | None = None
    metadata: Mapping[str, object] | None = None
    score: float | None = None
    vector_rank: int | None = None
    bm25_rank: int | None = None
    rerank_rank: int | None = None
    vector_score: float | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
    excerpt: str | None = None
    knowledge_type: str | None = None


ChatAgentEvent = (
    ChatAgentContentDelta | ChatAgentReasoningDelta | ChatAgentToolCall | ChatAgentReference
)


@dataclass(frozen=True, slots=True)
class ChatAgentRequest:
    """Input passed to a chat Agent runner."""

    owner_user_id: str
    session_id: str
    messages: Sequence[ChatMessageRecord]
    accessible_knowledge_base_ids: tuple[str, ...]
    system_prompt: str
    skills: tuple[SelectedChatSkill, ...] = ()


class LoadSkillInput(BaseModel):
    """Arguments accepted by the progressive Skill loading tool."""

    skill_name: str = Field(description="要加载的 Skill name，必须来自 Available Skills。")


class ChatAgentRunner(Protocol):
    """Agent execution boundary used by the streaming chat service."""

    def stream(self, request: ChatAgentRequest) -> AsyncIterator[ChatAgentEvent]:
        """Stream Agent events for a chat request."""
        ...


class ChatStreamingService:
    """Persist chat messages and translate Agent events into shared SSE payloads."""

    def __init__(
        self,
        *,
        repositories: MemoryRepositories,
        agent_runner: ChatAgentRunner,
        memory_service: ChatMemoryService | None = None,
    ) -> None:
        self._repositories = repositories
        self._agent_runner = agent_runner
        self._memory_service = memory_service

    async def stream_message(
        self,
        *,
        owner_user_id: str,
        session: ChatSessionRecord,
        content: str,
        metadata: JsonDict | None = None,
        accessible_knowledge_base_ids: Sequence[str],
    ) -> AsyncIterator[dict[str, object]]:
        started_at = monotonic()
        message_content = content.strip()
        if not message_content:
            yield _error_event("VALIDATION_INVALID_ARGUMENT")
            return
        emit_event(logger, "agent.chat.started", sessionId=session.id)

        history = await self._repositories.chat.list_messages(
            owner_user_id=owner_user_id,
            session_id=session.id,
        )
        system_prompt, selected_skills = await self.build_agent_configuration(
            owner_user_id=owner_user_id
        )
        prepared_messages: Sequence[ChatMessageRecord] | None = None
        if self._memory_service is not None:
            try:
                prepared = await self._memory_service.prepare_message(
                    owner_user_id=owner_user_id,
                    session=session,
                    history=history,
                    system_prompt=system_prompt,
                    content=message_content,
                )
            except ChatContextLimitReached:
                yield _error_event("CHAT_CONTEXT_LIMIT_REACHED")
                return
            session = prepared.session
            system_prompt = prepared.system_prompt
            prepared_messages = prepared.messages

        user_message = await self._repositories.chat.append_message(
            owner_user_id=owner_user_id,
            message_id=f"message_{uuid4().hex}",
            session_id=session.id,
            role="user",
            content=message_content,
            metadata=metadata or {},
        )
        await self._maybe_generate_chat_title(
            owner_user_id=owner_user_id,
            session=session,
            message_content=message_content,
        )
        history = await self._repositories.chat.list_messages(
            owner_user_id=owner_user_id,
            session_id=session.id,
        )
        model_messages = (
            [*prepared_messages[:-1], user_message] if prepared_messages is not None else history
        )
        request = ChatAgentRequest(
            owner_user_id=owner_user_id,
            session_id=session.id,
            messages=model_messages if model_messages else [user_message],
            accessible_knowledge_base_ids=tuple(accessible_knowledge_base_ids),
            system_prompt=system_prompt,
            skills=selected_skills,
        )
        answer_parts: list[str] = []
        tool_call_ids: list[str] = []
        citations: list[dict[str, object]] = []
        reasoning_parts: list[str] = []
        sequence = 0

        try:
            async for event in self._agent_runner.stream(request):
                if isinstance(event, ChatAgentContentDelta):
                    if event.delta == "":
                        continue
                    answer_parts.append(event.delta)
                    for character in event.delta:
                        sequence += 1
                        yield _sse_event(
                            "content.delta",
                            {
                                "delta": character,
                                "sequence": sequence,
                            },
                        )
                elif isinstance(event, ChatAgentReasoningDelta):
                    if event.delta == "":
                        continue
                    reasoning_parts.append(event.delta)
                    sequence += 1
                    yield _sse_event(
                        "reasoning.delta", {"delta": event.delta, "sequence": sequence}
                    )
                elif isinstance(event, ChatAgentToolCall):
                    await self._persist_tool_call_audit(
                        owner_user_id=owner_user_id,
                        session_id=session.id,
                        event=event,
                    )
                    _append_unique(tool_call_ids, event.id)
                    payload: dict[str, object] = {
                        "id": event.id,
                        "name": event.name,
                        "status": event.status,
                    }
                    if event.input is not None:
                        payload["input"] = event.input
                    if event.output is not None:
                        payload["output"] = event.output
                    yield _sse_event("tool.call", {"toolCall": payload})
                else:
                    reference = _reference_payload(event)
                    citations.append(reference)
                    yield _sse_event("reference.source", {"reference": reference})

            answer = "".join(answer_parts).strip()
            assistant_message = await self._repositories.chat.append_message(
                owner_user_id=owner_user_id,
                message_id=f"message_{uuid4().hex}",
                session_id=session.id,
                role="assistant",
                content=answer,
                metadata={
                    "citations": citations,
                    "reasoning": reasoning_parts,
                    "toolCallIds": tool_call_ids,
                },
            )
            refreshed_session = (
                await self._repositories.chat.get_session(
                    owner_user_id=owner_user_id,
                    session_id=session.id,
                )
            ) or session
            if self._memory_service is not None:
                refreshed_history = await self._repositories.chat.list_messages(
                    owner_user_id=owner_user_id,
                    session_id=session.id,
                )
                refreshed_session = await self._memory_service.refresh_usage(
                    owner_user_id=owner_user_id,
                    session=refreshed_session,
                    history=refreshed_history,
                    system_prompt=await self.build_system_prompt(owner_user_id=owner_user_id),
                )
            yield _sse_event(
                "complete",
                {
                    "result": {
                        "session": _chat_session_payload(
                            refreshed_session,
                            self._memory_service.context_window_tokens
                            if self._memory_service is not None
                            else 131072,
                        ),
                        "message": _chat_message_payload(assistant_message),
                    }
                },
            )
            emit_event(
                logger,
                "agent.chat.completed",
                sessionId=session.id,
                toolCallCount=len(tool_call_ids),
                durationMs=elapsed_ms(started_at),
            )
        except Exception as exc:
            emit_event(
                logger,
                "agent.chat.failed",
                sessionId=session.id,
                errorCategory=exc.__class__.__name__,
                durationMs=elapsed_ms(started_at),
            )
            yield _error_event("SYSTEM_INTERNAL_ERROR")
            return

    async def build_system_prompt(self, *, owner_user_id: str) -> str:
        system_prompt, _ = await self.build_agent_configuration(owner_user_id=owner_user_id)
        return system_prompt

    async def build_agent_configuration(
        self, *, owner_user_id: str
    ) -> tuple[str, tuple[SelectedChatSkill, ...]]:
        prompt_repository = self._repositories.chat_prompts
        skill_repository = self._repositories.chat_skills
        configuration_repository = self._repositories.chat_configurations
        if (
            prompt_repository is None
            or skill_repository is None
            or configuration_repository is None
        ):
            return build_chat_system_prompt(prompt_content=DEFAULT_CHAT_PROMPT_CONTENT), ()

        default_prompt = await prompt_repository.ensure_default(
            owner_user_id=owner_user_id,
            label=DEFAULT_CHAT_PROMPT_LABEL,
            content=DEFAULT_CHAT_PROMPT_CONTENT,
        )
        configuration = await configuration_repository.get_or_create(
            owner_user_id=owner_user_id,
            system_prompt_id=default_prompt.id,
            skill_ids=[],
        )
        selected_prompt = await prompt_repository.get(
            owner_user_id=owner_user_id,
            prompt_id=configuration.system_prompt_id,
        )
        skill_ids = list(dict.fromkeys(configuration.skill_ids))
        if selected_prompt is None:
            selected_prompt = default_prompt
            configuration = await configuration_repository.update(
                owner_user_id=owner_user_id,
                system_prompt_id=default_prompt.id,
                skill_ids=skill_ids,
            )

        selected_skills: list[SelectedChatSkill] = []
        valid_skill_ids: list[str] = []
        for skill_id in skill_ids:
            skill = await skill_repository.get(owner_user_id=owner_user_id, skill_id=skill_id)
            if skill is None:
                continue
            valid_skill_ids.append(skill.id)
            selected_skills.append(
                SelectedChatSkill(
                    name=skill.name,
                    description=skill.description,
                    content=skill.content,
                )
            )
        if valid_skill_ids != configuration.skill_ids:
            await configuration_repository.update(
                owner_user_id=owner_user_id,
                system_prompt_id=selected_prompt.id,
                skill_ids=valid_skill_ids,
            )
        return (
            build_chat_system_prompt(
                prompt_content=selected_prompt.content,
                skills=selected_skills,
            ),
            tuple(selected_skills),
        )

    async def _persist_tool_call_audit(
        self,
        *,
        owner_user_id: str,
        session_id: str,
        event: ChatAgentToolCall,
    ) -> None:
        repository = self._repositories.tool_call_audits
        if repository is None:
            return
        try:
            if event.status == "started":
                await repository.create_for_chat_session(
                    owner_user_id=owner_user_id,
                    audit_id=event.id,
                    chat_session_id=session_id,
                    tool_name=event.name,
                    arguments=_json_dict_or_empty(event.input),
                )
                return
            if event.status == "completed":
                audit = await repository.finalize(
                    owner_user_id=owner_user_id,
                    audit_id=event.id,
                    status="completed",
                    result_summary=_audit_summary(event.output),
                )
                if audit is None:
                    await self._create_and_finalize_missing_audit(
                        owner_user_id=owner_user_id,
                        session_id=session_id,
                        event=event,
                        result_summary=_audit_summary(event.output),
                    )
                return
            if event.status == "failed":
                error_message = _audit_error_summary(event.output)
                audit = await repository.finalize(
                    owner_user_id=owner_user_id,
                    audit_id=event.id,
                    status="failed",
                    error_message=error_message,
                )
                if audit is None:
                    await self._create_and_finalize_missing_audit(
                        owner_user_id=owner_user_id,
                        session_id=session_id,
                        event=event,
                        error_message=error_message,
                    )
        except Exception:
            return

    async def _create_and_finalize_missing_audit(
        self,
        *,
        owner_user_id: str,
        session_id: str,
        event: ChatAgentToolCall,
        result_summary: str | None = None,
        error_message: str | None = None,
    ) -> None:
        repository = self._repositories.tool_call_audits
        if repository is None:
            return
        await repository.create_for_chat_session(
            owner_user_id=owner_user_id,
            audit_id=event.id,
            chat_session_id=session_id,
            tool_name=event.name,
            arguments=_json_dict_or_empty(event.input),
        )
        await repository.finalize(
            owner_user_id=owner_user_id,
            audit_id=event.id,
            status="failed" if error_message is not None else "completed",
            result_summary=result_summary,
            error_message=error_message,
        )

    async def _maybe_generate_chat_title(
        self,
        *,
        owner_user_id: str,
        session: ChatSessionRecord,
        message_content: str,
    ) -> None:
        if session.title not in {None, "New chat"}:
            return
        await self._repositories.chat.update_session_title(
            owner_user_id=owner_user_id,
            session_id=session.id,
            title=_normalize_chat_title(message_content),
        )


class LangChainChatAgentRunner:
    """Default Agent runner using LangChain create_agent."""

    def __init__(
        self,
        *,
        llm_provider: LlmProvider,
        retrieval_tool: KnowledgeRetrievalTool,
        mcp_client: LocalMcpClient | None = None,
        mcp_client_provider: McpConnectionService | None = None,
    ) -> None:
        self._llm_provider = llm_provider
        self._retrieval_tool = retrieval_tool
        self._mcp_client = mcp_client
        self._mcp_client_provider = mcp_client_provider

    async def stream(self, request: ChatAgentRequest) -> AsyncIterator[ChatAgentEvent]:
        langchain_tool = create_langchain_knowledge_retrieval_tool(
            self._retrieval_tool,
            owner_user_id=request.owner_user_id,
            accessible_knowledge_base_ids=request.accessible_knowledge_base_ids,
        ) # 当前用户id只能访问对应权限的知识库数据
        tools = [langchain_tool, create_current_time_tool()]
        if request.skills:
            tools.append(create_load_skill_tool(request.skills))
        mcp_client = self._mcp_client
        if self._mcp_client_provider is not None:
            mcp_client = await self._mcp_client_provider.client_for_user(
                owner_user_id=request.owner_user_id
            )
        if mcp_client is not None:
            await mcp_client.discover_tools()
            tools.extend(await mcp_client.get_langchain_tools())
        agent = _create_langchain_agent(
            model=cast(Any, self._llm_provider.create_chat_model()),
            tools=tools,
            system_prompt=(request.system_prompt),
        )
        messages = [
            {"role": message.role, "content": message.content}
            for message in request.messages
            if message.role in {"user", "assistant"}
        ]

        async for raw_event in agent.astream_events(
            cast(Any, {"messages": messages}),
            version="v2",
        ):
            parsed = _agent_event_from_langchain_event(cast(Mapping[str, object], raw_event))
            if parsed is None:
                continue
            if isinstance(parsed, list):
                for item in parsed:
                    yield item
            else:
                yield parsed


def create_load_skill_tool(skills: Sequence[SelectedChatSkill]) -> StructuredTool:
    """Create a request-scoped tool that can load only the selected user's Skills."""
    skill_registry = {skill.name: skill for skill in skills}
    available_names = ", ".join(skill_registry)

    async def load_skill(skill_name: str) -> str:
        requested_name = skill_name.strip()
        skill = skill_registry.get(requested_name)
        if skill is None:
            return (
                f"Skill '{requested_name}' 不可用。当前可加载的 Skill: {available_names or '无'}。"
            )
        return f"Loaded skill: {skill.name}\n\n{skill.content}"

    return StructuredTool.from_function(
        coroutine=load_skill,
        name="load_skill",
        description=(
            "按 name 加载当前会话已选择 Skill 的完整指令。仅当用户任务与 Available Skills "
            f"中的描述匹配时调用。可用 name: {available_names}。"
        ),
        args_schema=LoadSkillInput,
    )


def _agent_event_from_langchain_event(
    event: Mapping[str, object],
) -> ChatAgentEvent | list[ChatAgentEvent] | None:
    event_name = event.get("event")
    data = cast(Mapping[str, object], event.get("data") or {})
    run_id = str(event.get("run_id") or f"tool_call_{uuid4().hex}")
    name = str(event.get("name") or "tool")

    if event_name == "on_tool_start":
        return ChatAgentToolCall(
            id=run_id,
            name=name,
            status="started",
            input=data.get("input"),
        )
    if event_name == "on_tool_end":
        output = data.get("output")
        events: list[ChatAgentEvent] = [
            ChatAgentToolCall(
                id=run_id,
                name=name,
                status="completed",
                output=_tool_event_output(name, output),
            )
        ]
        events.extend(_references_from_tool_output(output))
        return events
    if event_name == "on_tool_error":
        return ChatAgentToolCall(
            id=run_id,
            name=name,
            status="failed",
            output=_jsonable(data.get("error")),
        )
    if event_name == "on_chat_model_stream":
        return _content_events_from_chunk(data.get("chunk"))
    if event_name == "on_chain_stream" and name == "model":
        return _content_events_from_chunk(data.get("chunk"))
    return None


def _tool_event_output(tool_name: str, output: object) -> object:
    if tool_name == "load_skill":
        content = getattr(output, "content", output)
        if isinstance(content, str):
            summary = content.partition("\n")[0].strip()
            return {"summary": summary or "Skill loaded"}
    return _jsonable(output)


def _content_events_from_chunk(chunk: object) -> ChatAgentEvent | list[ChatAgentEvent] | None:
    content = _extract_content(chunk)
    reasoning = _extract_reasoning(chunk)
    events: list[ChatAgentEvent] = []
    if content:
        events.append(ChatAgentContentDelta(content))
    if reasoning:
        events.append(ChatAgentReasoningDelta(reasoning))
    if not events:
        return None
    return events[0] if len(events) == 1 else events


def _extract_reasoning(value: object) -> str:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        for key in ("reasoning_content", "reasoning"):
            if isinstance(mapping.get(key), str):
                return cast(str, mapping[key])
    additional = getattr(cast(object, value), "additional_kwargs", None)
    if isinstance(additional, Mapping):
        return _extract_reasoning(cast(Mapping[str, object], additional))
    return ""


def _create_langchain_agent(**kwargs: object) -> Any:
    agents_module = import_module("langchain.agents")
    create_agent_fn = cast(Callable[..., Any], cast(Any, agents_module).create_agent)
    return create_agent_fn(**kwargs)


def _extract_content(value: object) -> str:
    update = cast(object, getattr(value, "update", None))
    if isinstance(update, Mapping):
        return _extract_content(cast(Mapping[str, object], update))
    content = cast(object, getattr(value, "content", None))
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_content_item_to_text(item) for item in cast(Sequence[object], content))
    if isinstance(value, list):
        return "".join(_extract_content(item) for item in cast(Sequence[object], value))
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        if "messages" in mapping:
            return _extract_content(mapping["messages"])
        if "model" in mapping:
            return _extract_content(mapping["model"])
        if "chunk" in mapping:
            return _extract_content(mapping["chunk"])
    return ""


def _content_item_to_text(item: object) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, Mapping):
        mapping = cast(Mapping[str, object], item)
        text = mapping.get("text")
        if isinstance(text, str):
            return text
    return ""


def _json_dict_or_empty(value: object | None) -> JsonDict:
    normalized = _jsonable(value)
    return cast(JsonDict, normalized) if isinstance(normalized, dict) else {}


def _audit_summary(value: object | None) -> str:
    encoded = json.dumps(_jsonable(value), ensure_ascii=True, separators=(",", ":"), default=str)
    return encoded[:2000]


def _audit_error_summary(value: object | None) -> str:
    return re.sub(r"(?:sk-[A-Za-z0-9_-]+|AKID[A-Za-z0-9]+)", "[redacted]", _audit_summary(value))


def _references_from_tool_output(output: object) -> list[ChatAgentReference]:
    mapping = _tool_output_mapping(output)
    if mapping is None:
        return []
    citations_value = mapping.get("citations")
    if not isinstance(citations_value, Sequence) or isinstance(citations_value, (str, bytes)):
        return []
    references: list[ChatAgentReference] = []
    for citation in cast(Sequence[object], citations_value):
        if isinstance(citation, Mapping):
            citation_map = cast(Mapping[str, object], citation)
            references.append(
                ChatAgentReference(
                    id=str(citation_map.get("id") or citation_map.get("chunkId") or uuid4().hex),
                    title=str(
                        citation_map.get("title")
                        or citation_map.get("source")
                        or "Knowledge source"
                    ),
                    source_type=str(citation_map.get("sourceType") or "knowledge-base"),
                    chunk_id=_optional_str(citation_map.get("chunkId")),
                    document_id=_optional_str(citation_map.get("documentId")),
                    knowledge_base_id=_optional_str(citation_map.get("knowledgeBaseId")),
                    source=_optional_str(citation_map.get("source")),
                    uri=_optional_str(citation_map.get("uri")),
                    metadata=cast(Mapping[str, object] | None, citation_map.get("metadata")),
                    score=_optional_float(citation_map.get("score")),
                    vector_rank=_optional_int(citation_map.get("vectorRank")),
                    bm25_rank=_optional_int(citation_map.get("bm25Rank")),
                    rerank_rank=_optional_int(citation_map.get("rerankRank")),
                    vector_score=_optional_float(citation_map.get("vectorScore")),
                    bm25_score=_optional_float(citation_map.get("bm25Score")),
                    rrf_score=_optional_float(citation_map.get("rrfScore")),
                    rerank_score=_optional_float(citation_map.get("rerankScore")),
                    excerpt=_optional_str(citation_map.get("excerpt")),
                    knowledge_type=_optional_str(citation_map.get("knowledgeType")),
                )
            )
    return references


def _tool_output_mapping(output: object) -> Mapping[str, object] | None:
    if isinstance(output, Mapping):
        return cast(Mapping[str, object], output)
    content = getattr(output, "content", None)
    if not isinstance(content, str):
        return None
    try:
        parsed: object = json.loads(content)
    except json.JSONDecodeError:
        return None
    return cast(Mapping[str, object], parsed) if isinstance(parsed, Mapping) else None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _jsonable(item) for key, item in mapping.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_jsonable(item) for item in cast(Sequence[object], value)]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def encode_sse(event: Mapping[str, object]) -> str:
    """Encode a shared SSE event payload as one text/event-stream frame."""
    event_type = str(event["type"])
    return f"event: {event_type}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


def _sse_event(event_type: str, payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": f"evt_{uuid4().hex}",
        "type": event_type,
        "channel": "chat",
        "timestamp": _now_iso(),
        **payload,
    }


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


def _reference_payload(reference: ChatAgentReference) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": reference.id,
        "title": reference.title,
        "sourceType": reference.source_type,
    }
    optional_values = {
        "chunkId": reference.chunk_id,
        "documentId": reference.document_id,
        "knowledgeBaseId": reference.knowledge_base_id,
        "source": reference.source,
        "uri": reference.uri,
        "metadata": dict(reference.metadata or {}),
        "score": reference.score,
        "vectorRank": reference.vector_rank,
        "bm25Rank": reference.bm25_rank,
        "rerankRank": reference.rerank_rank,
        "vectorScore": reference.vector_score,
        "bm25Score": reference.bm25_score,
        "rrfScore": reference.rrf_score,
        "rerankScore": reference.rerank_score,
        "excerpt": reference.excerpt,
        "knowledgeType": reference.knowledge_type,
    }
    for key, value in optional_values.items():
        if value is not None:
            payload[key] = value
    return payload


def _chat_session_payload(
    record: ChatSessionRecord, context_window_tokens: int
) -> dict[str, object]:
    return {
        "id": record.id,
        "ownerUserId": record.owner_user_id,
        "title": record.title or "New chat",
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
        "memory": memory_payload(record, context_window_tokens),
    }


def _chat_message_payload(message: ChatMessageRecord) -> dict[str, object]:
    return {
        "id": message.id,
        "ownerUserId": message.owner_user_id,
        "sessionId": message.session_id,
        "role": message.role,
        "content": message.content,
        "metadata": message.metadata,
        "createdAt": message.created_at.isoformat(),
    }


def _normalize_chat_title(title: str) -> str:
    normalized = " ".join(title.split())
    if normalized == "":
        return "New chat"
    return normalized[:80]


def _append_unique(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
