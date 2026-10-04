from __future__ import annotations

# pyright: reportPrivateUsage=false
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from alembic import command
from alembic.config import Config
from langchain_core.messages import AIMessage
from langgraph.types import Command

from super_ai.api.app import create_app
from super_ai.chat.configuration import SelectedChatSkill, build_chat_system_prompt
from super_ai.chat.streaming import (
    ChatAgentContentDelta,
    ChatAgentEvent,
    ChatAgentReasoningDelta,
    ChatAgentReference,
    ChatAgentRequest,
    ChatAgentToolCall,
    ChatStreamingService,
    _agent_event_from_langchain_event,
    create_load_skill_tool,
)
from super_ai.memory.repositories import ChatMessageRecord, ChatSessionRecord, MemoryRepositories


@dataclass
class FakeChatAgentRunner:
    events: list[ChatAgentEvent]
    error: Exception | None = None

    def __post_init__(self) -> None:
        self.requests: list[ChatAgentRequest] = []

    async def stream(self, request: ChatAgentRequest) -> AsyncIterator[ChatAgentEvent]:
        self.requests.append(request)
        for event in self.events:
            yield event
        if self.error is not None:
            raise self.error


@dataclass(frozen=True)
class ToolMessageLike:
    content: str


def test_agent_event_adapter_parses_tool_message_citations() -> None:
    citation = {
        "id": "chunk_1",
        "title": "restart.md",
        "sourceType": "knowledge-base",
        "documentId": "doc_1",
        "knowledgeBaseId": "kb_1",
        "excerpt": "Restart the service.",
        "knowledgeType": "sop",
    }
    tool_output = ToolMessageLike(content=json.dumps({"citations": [citation]}))
    tool_event = _agent_event_from_langchain_event(
        {
            "event": "on_tool_end",
            "run_id": "tool_1",
            "name": "knowledge_retrieval",
            "data": {"output": tool_output},
        }
    )
    chain_event = _agent_event_from_langchain_event(
        {
            "event": "on_chain_stream",
            "name": "tools",
            "data": {"chunk": {"citations": [citation]}},
        }
    )

    assert isinstance(tool_event, list)
    assert isinstance(tool_event[1], ChatAgentReference)
    assert tool_event[1].excerpt == "Restart the service."
    assert tool_event[1].knowledge_type == "sop"
    assert chain_event is None


def test_agent_event_adapter_summarizes_loaded_skill_for_the_ui() -> None:
    event = _agent_event_from_langchain_event(
        {
            "event": "on_tool_end",
            "run_id": "tool_skill",
            "name": "load_skill",
            "data": {
                "output": ToolMessageLike(
                    content="Loaded skill: log-analysis\n\nFULL_SKILL_BODY"
                )
            },
        }
    )

    assert isinstance(event, list)
    assert event[0] == ChatAgentToolCall(
        id="tool_skill",
        name="load_skill",
        status="completed",
        output={"summary": "Loaded skill: log-analysis"},
    )


def test_agent_event_adapter_parses_langgraph_model_command() -> None:
    parsed = _agent_event_from_langchain_event(
        {
            "event": "on_chain_stream",
            "name": "model",
            "data": {
                "chunk": [Command(update={"messages": [AIMessage(content="Hello from Qwen.")]})]
            },
        }
    )

    assert parsed == ChatAgentContentDelta("Hello from Qwen.")


@pytest.mark.asyncio
async def test_streaming_chat_emits_sse_events_and_persists_messages(
    migrated_database_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    logging.getLogger("super_ai.chat.streaming").disabled = False
    caplog.set_level(logging.INFO, logger="super_ai.chat.streaming")
    runner = FakeChatAgentRunner(
        events=[
            ChatAgentReasoningDelta("I will check the runbook first."),
            ChatAgentToolCall(
                id="tool_call_1",
                name="knowledge_retrieval",
                status="started",
                input={"query": "restart api"},
            ),
            ChatAgentToolCall(
                id="tool_call_1",
                name="knowledge_retrieval",
                status="completed",
                output={"results": ["chunk_1"]},
            ),
            ChatAgentReference(
                id="chunk_1",
                title="runbook.md",
                source_type="knowledge-base",
                chunk_id="chunk_1",
                document_id="doc_1",
                knowledge_base_id="kb_user",
                source="runbook.md",
                metadata={"section": "restart"},
                score=0.91,
                excerpt="Restart the API by applying the approved runbook.",
                knowledge_type="sop",
            ),
            ChatAgentContentDelta("Use the "),
            ChatAgentContentDelta("restart runbook."),
        ]
    )
    app = create_app(database_url=migrated_database_url, chat_agent_runner=runner)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user = await _register(client, "stream-owner@example.com", "Stream Owner")
        headers = {**_auth_headers(user["accessToken"]), "X-Request-ID": "chat-observe"}
        session = (await client.post("/chat/sessions", headers=headers, json={})).json()["data"]

        stream_response = await client.post(
            f"/chat/sessions/{session['id']}/messages:stream",
            headers=headers,
            json={"content": "How do I restart the API?"},
        )
        detail_response = await client.get(f"/chat/sessions/{session['id']}", headers=headers)
        audits_response = await client.get(
            f"/chat/sessions/{session['id']}/tool-call-audits",
            headers=headers,
        )

    assert stream_response.status_code == 200
    assert stream_response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(stream_response.text)
    assert [event["event"] for event in events[:4]] == [
        "reasoning.delta",
        "tool.call",
        "tool.call",
        "reference.source",
    ]
    assert events[-1]["event"] == "complete"
    assert events[0]["data"]["delta"] == "I will check the runbook first."
    assert events[1]["data"]["toolCall"]["status"] == "started"
    assert events[3]["data"]["reference"]["chunkId"] == "chunk_1"
    assert events[3]["data"]["reference"]["knowledgeType"] == "sop"
    assert events[3]["data"]["reference"]["excerpt"] == (
        "Restart the API by applying the approved runbook."
    )
    content_events = [event for event in events if event["event"] == "content.delta"]
    assert "".join(event["data"]["delta"] for event in content_events) == (
        "Use the restart runbook."
    )
    assert all(len(event["data"]["delta"]) == 1 for event in content_events)
    assert [event["data"]["sequence"] for event in content_events] == list(
        range(2, len(content_events) + 2)
    )
    assert events[-1]["data"]["result"]["message"]["content"] == "Use the restart runbook."
    assert runner.requests[0].owner_user_id == user["user"]["id"]
    assert runner.requests[0].accessible_knowledge_base_ids == (f"kb_{user['user']['id']}",)
    assert runner.requests[0].messages[-1].content == "How do I restart the API?"

    history = detail_response.json()["data"]["messages"]
    assert [message["role"] for message in history] == ["user", "assistant"]
    assert history[0]["content"] == "How do I restart the API?"
    assert history[1]["content"] == "Use the restart runbook."
    assert history[1]["metadata"]["toolCallIds"] == ["tool_call_1"]
    assert history[1]["metadata"]["reasoning"] == ["I will check the runbook first."]
    assert history[1]["metadata"]["citations"][0]["chunkId"] == "chunk_1"
    assert history[1]["metadata"]["citations"][0]["knowledgeType"] == "sop"
    assert audits_response.status_code == 200
    audit = audits_response.json()["data"]["items"][0]
    assert audit["id"] == "tool_call_1"
    assert audit["sessionId"] == session["id"]
    assert audit["status"] == "completed"
    assert audit["arguments"] == {"query": "restart api"}
    assert audit["resultSummary"] == '{"results":["chunk_1"]}'
    agent_events = [
        json.loads(record.message)
        for record in caplog.records
        if record.message.startswith("{") and "agent.chat" in record.message
    ]
    assert [event["event"] for event in agent_events] == [
        "agent.chat.started",
        "agent.chat.completed",
    ]
    assert all(event["requestId"] == "chat-observe" for event in agent_events)
    assert "How do I restart the API?" not in "\n".join(record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_chat_configuration_is_validated_and_isolated_by_owner(
    migrated_database_url: str,
) -> None:
    runner = FakeChatAgentRunner(events=[ChatAgentContentDelta("收到。")])
    app = create_app(
        database_url=migrated_database_url, chat_agent_runner=runner
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user_a = await _register(client, "prompt-owner@example.com", "Prompt Owner")
        user_b = await _register(client, "prompt-other@example.com", "Prompt Other")
        headers_a = _auth_headers(user_a["accessToken"])
        headers_b = _auth_headers(user_b["accessToken"])

        default_a = await client.get("/chat/configuration", headers=headers_a)
        default_b = await client.get("/chat/configuration", headers=headers_b)
        created_prompt = await client.post(
            "/chat/prompts",
            headers=headers_a,
            json={
                "label": "自定义诊断提示词",
                "content": "回答前必须遵守 PROMPT_MARKER。",
            },
        )
        prompt_id = created_prompt.json()["data"]["id"]
        edited_prompt = await client.put(
            f"/chat/prompts/{prompt_id}",
            headers=headers_a,
            json={
                "label": "已修改诊断提示词",
                "content": "回答前必须遵守 PROMPT_MARKER_EDITED。",
            },
        )
        uploaded_skill = await client.post(
            "/chat/skills",
            headers=headers_a,
            files={
                "file": (
                    "SKILL.md",
                    (
                        b"---\nname: custom-diagnostic\n"
                        b"description: Apply the custom diagnostic workflow "
                        b"when explicitly requested.\n"
                        b"---\n\n# Custom Skill\n\nAlways apply SKILL_MARKER."
                    ),
                    "text/markdown",
                )
            },
        )
        invalid_skill = await client.post(
            "/chat/skills",
            headers=headers_a,
            files={"file": ("Custom.md", b"# Invalid", "text/markdown")},
        )
        skill_id = uploaded_skill.json()["data"]["id"]
        updated = await client.put(
            "/chat/configuration",
            headers=headers_a,
            json={"systemPromptId": prompt_id, "skillIds": [skill_id]},
        )
        invalid = await client.put(
            "/chat/configuration",
            headers=headers_a,
            json={
                "systemPromptId": default_b.json()["data"]["selection"]["systemPromptId"],
                "skillIds": [],
            },
        )
        session = (await client.post("/chat/sessions", headers=headers_a, json={})).json()["data"]
        stream = await client.post(
            f"/chat/sessions/{session['id']}/messages:stream",
            headers=headers_a,
            json={"content": "验证装配是否生效"},
        )
        deleted_skill = await client.delete(f"/chat/skills/{skill_id}", headers=headers_a)
        after_skill_delete = await client.get("/chat/configuration", headers=headers_a)
        deleted_prompt = await client.delete(f"/chat/prompts/{prompt_id}", headers=headers_a)
        after_prompt_delete = await client.get("/chat/configuration", headers=headers_a)
        persisted_b = await client.get("/chat/configuration", headers=headers_b)

    assert default_a.status_code == 200
    default_prompts = default_a.json()["data"]["prompts"]
    assert default_prompts[0]["content"]
    assert default_a.json()["data"]["skills"] == []
    assert created_prompt.status_code == 201
    assert edited_prompt.status_code == 200
    assert edited_prompt.json()["data"]["content"] == "回答前必须遵守 PROMPT_MARKER_EDITED。"
    assert uploaded_skill.status_code == 201
    assert uploaded_skill.json()["data"]["filename"] == "SKILL.md"
    assert uploaded_skill.json()["data"]["name"] == "custom-diagnostic"
    assert "custom diagnostic workflow" in uploaded_skill.json()["data"]["description"]
    assert invalid_skill.status_code == 400
    assert invalid_skill.json()["error"]["code"] == "VALIDATION_INVALID_ARGUMENT"
    assert updated.status_code == 200
    selection = updated.json()["data"]["selection"]
    assert selection["systemPromptId"] == prompt_id
    assert selection["skillIds"] == [skill_id]
    assert selection["updatedAt"]
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "VALIDATION_INVALID_ARGUMENT"
    assert stream.status_code == 200
    assert runner.requests
    assert "PROMPT_MARKER_EDITED" in runner.requests[0].system_prompt
    assert "custom-diagnostic" in runner.requests[0].system_prompt
    assert "custom diagnostic workflow" in runner.requests[0].system_prompt
    assert "SKILL_MARKER" not in runner.requests[0].system_prompt
    assert runner.requests[0].skills[0].name == "custom-diagnostic"
    assert "SKILL_MARKER" in runner.requests[0].skills[0].content
    assert "get_current_time" in runner.requests[0].system_prompt
    assert deleted_skill.status_code == 200
    assert skill_id not in after_skill_delete.json()["data"]["selection"]["skillIds"]
    assert deleted_prompt.status_code == 200
    assert after_prompt_delete.json()["data"]["selection"]["systemPromptId"] != prompt_id
    assert persisted_b.json()["data"]["selection"] == default_b.json()["data"]["selection"]


@pytest.mark.asyncio
async def test_load_skill_tool_progressively_discloses_only_selected_content() -> None:
    selected = SelectedChatSkill(
        name="log-analysis",
        description="Analyze real logs when the user requests log investigation.",
        content="# Log Analysis\n\nSKILL_BODY_MARKER",
    )
    prompt = build_chat_system_prompt(prompt_content="回答用户问题。", skills=[selected])
    tool = create_load_skill_tool([selected])

    loaded = await tool.ainvoke({"skill_name": "log-analysis"})
    missing = await tool.ainvoke({"skill_name": "other-user-skill"})

    assert "log-analysis" in prompt
    assert selected.description in prompt
    assert "SKILL_BODY_MARKER" not in prompt
    assert "SKILL_BODY_MARKER" in loaded
    assert "不可用" in missing


@pytest.mark.asyncio
async def test_chat_tool_call_audits_are_forbidden_outside_owner_scope(
    migrated_database_url: str,
) -> None:
    runner = FakeChatAgentRunner(events=[])
    app = create_app(database_url=migrated_database_url, chat_agent_runner=runner)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user_a = await _register(client, "audit-owner@example.com", "Audit Owner")
        user_b = await _register(client, "audit-other@example.com", "Audit Other")
        session = (
            await client.post(
                "/chat/sessions",
                headers=_auth_headers(user_a["accessToken"]),
                json={},
            )
        ).json()["data"]

        response = await client.get(
            f"/chat/sessions/{session['id']}/tool-call-audits",
            headers=_auth_headers(user_b["accessToken"]),
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "AUTH_FORBIDDEN"


@pytest.mark.asyncio
async def test_failed_chat_tool_call_audit_redacts_provider_secret(
    migrated_database_url: str,
) -> None:
    runner = FakeChatAgentRunner(
        events=[
            ChatAgentToolCall(
                id="tool_call_failed",
                name="knowledge_retrieval",
                status="started",
                input={"query": "restart api"},
            ),
            ChatAgentToolCall(
                id="tool_call_failed",
                name="knowledge_retrieval",
                status="failed",
                output="provider failed with sk-secret-value",
            ),
        ]
    )
    app = create_app(database_url=migrated_database_url, chat_agent_runner=runner)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user = await _register(client, "audit-error@example.com", "Audit Error")
        headers = _auth_headers(user["accessToken"])
        session = (await client.post("/chat/sessions", headers=headers, json={})).json()["data"]

        await client.post(
            f"/chat/sessions/{session['id']}/messages:stream",
            headers=headers,
            json={"content": "Use a tool"},
        )
        audits_response = await client.get(
            f"/chat/sessions/{session['id']}/tool-call-audits",
            headers=headers,
        )

    audit = audits_response.json()["data"]["items"][0]
    assert audit["status"] == "failed"
    assert "sk-secret-value" not in audit["errorMessage"]
    assert "[redacted]" in audit["errorMessage"]


@pytest.mark.asyncio
async def test_streaming_chat_rejects_cross_tenant_session_before_agent_runs(
    migrated_database_url: str,
) -> None:
    runner = FakeChatAgentRunner(events=[])
    app = create_app(database_url=migrated_database_url, chat_agent_runner=runner)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user_a = await _register(client, "stream-a@example.com", "Stream A")
        user_b = await _register(client, "stream-b@example.com", "Stream B")
        session = (
            await client.post(
                "/chat/sessions",
                headers=_auth_headers(user_a["accessToken"]),
                json={"title": "Private"},
            )
        ).json()["data"]

        response = await client.post(
            f"/chat/sessions/{session['id']}/messages:stream",
            headers=_auth_headers(user_b["accessToken"]),
            json={"content": "cross tenant"},
        )
        owner_detail = await client.get(
            f"/chat/sessions/{session['id']}",
            headers=_auth_headers(user_a["accessToken"]),
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "AUTH_FORBIDDEN"
    assert runner.requests == []
    assert owner_detail.json()["data"]["messages"] == []


@pytest.mark.asyncio
async def test_streaming_chat_emits_safe_error_without_partial_assistant_message(
    migrated_database_url: str,
) -> None:
    runner = FakeChatAgentRunner(
        events=[ChatAgentContentDelta("partial secret")],
        error=RuntimeError("provider failed with sk-secret"),
    )
    app = create_app(database_url=migrated_database_url, chat_agent_runner=runner)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user = await _register(client, "stream-error@example.com", "Stream Error")
        headers = _auth_headers(user["accessToken"])
        session = (await client.post("/chat/sessions", headers=headers, json={})).json()["data"]

        response = await client.post(
            f"/chat/sessions/{session['id']}/messages:stream",
            headers=headers,
            json={"content": "Will this fail?"},
        )
        detail_response = await client.get(f"/chat/sessions/{session['id']}", headers=headers)

    assert response.status_code == 200
    assert "sk-secret" not in response.text
    events = _parse_sse(response.text)
    assert all(event["event"] == "content.delta" for event in events[:-1])
    assert "".join(event["data"]["delta"] for event in events[:-1]) == "partial secret"
    assert events[-1]["event"] == "error"
    assert events[-1]["data"]["error"]["code"] == "SYSTEM_INTERNAL_ERROR"
    assert [message["role"] for message in detail_response.json()["data"]["messages"]] == ["user"]


@pytest.mark.asyncio
async def test_streaming_chat_emits_error_when_assistant_persistence_fails() -> None:
    session = ChatSessionRecord(
        id="chat_1",
        owner_user_id="user_1",
        title="New chat",
        created_at=_now(),
        updated_at=_now(),
    )
    chat_repository = FailingAssistantChatRepository(session)
    service = ChatStreamingService(
        repositories=MemoryRepositories(
            chat=cast(Any, chat_repository),
            documents=cast(Any, object()),
            document_index_tasks=cast(Any, object()),
            diagnostics=cast(Any, object()),
        ),
        agent_runner=FakeChatAgentRunner(events=[ChatAgentContentDelta("partial answer")]),
    )

    events = [
        event
        async for event in service.stream_message(
            owner_user_id="user_1",
            session=session,
            content="Persist this",
            accessible_knowledge_base_ids=("kb_user_1",),
        )
    ]

    assert all(event["type"] == "content.delta" for event in events[:-1])
    assert "".join(cast(str, event["delta"]) for event in events[:-1]) == "partial answer"
    assert events[-1]["type"] == "error"
    error_payload = cast(dict[str, Any], events[-1]["error"])
    assert error_payload["code"] == "SYSTEM_INTERNAL_ERROR"
    assert [message.role for message in chat_repository.messages] == ["user"]


async def _register(client: httpx.AsyncClient, email: str, display_name: str) -> dict[str, Any]:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "displayName": display_name,
            "password": "correct horse battery staple",
        },
    )
    return response.json()["data"]


def _auth_headers(token: object) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _parse_sse(text: str) -> list[dict[str, Any]]:
    import json

    events: list[dict[str, Any]] = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        events.append({"event": fields["event"], "data": json.loads(fields["data"])})
    return events


class FailingAssistantChatRepository:
    def __init__(self, session: ChatSessionRecord) -> None:
        self.session = session
        self.messages: list[ChatMessageRecord] = []

    async def create_session(
        self,
        **_kwargs: object,
    ) -> ChatSessionRecord:
        return self.session

    async def get_session(
        self,
        **_kwargs: object,
    ) -> ChatSessionRecord | None:
        return self.session

    async def update_session_title(
        self,
        **_kwargs: object,
    ) -> ChatSessionRecord | None:
        return self.session

    async def list_sessions(
        self,
        **_kwargs: object,
    ) -> list[ChatSessionRecord]:
        return [self.session]

    async def append_message(
        self,
        *,
        owner_user_id: str,
        message_id: str,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, object] | None = None,
        **_kwargs: object,
    ) -> ChatMessageRecord:
        if role == "assistant":
            raise RuntimeError("database unavailable")
        message = ChatMessageRecord(
            id=message_id,
            owner_user_id=owner_user_id,
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata or {},
            created_at=_now(),
        )
        self.messages.append(message)
        return message

    async def clear_messages(self, **_kwargs: object) -> int:
        return 0

    async def delete_session(self, **_kwargs: object) -> bool:
        return False

    async def list_messages(
        self,
        **_kwargs: object,
    ) -> list[ChatMessageRecord]:
        return self.messages


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "stream-rag-chat-api.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"
