from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config

from super_ai.api.app import create_app
from super_ai.jobs import BackgroundJobRuntime
from super_ai.mcp_client import LocalMcpClient, McpToolDefinition
from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.extended_sqlite import SQLiteBackgroundJobRepository
from super_ai.vector_store import MilvusHealthCheckResult


class FakeVectorStore:
    def health_check(self) -> MilvusHealthCheckResult:
        return MilvusHealthCheckResult(True, "http://milvus.test", "chunks", 1.0)


@pytest.mark.asyncio
async def test_background_runtime_recovers_leases_persists_events_and_retries(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    repository = SQLiteBackgroundJobRepository(create_memory_session_factory(engine))
    handled: list[str] = []

    async def handler(context: Any) -> None:
        handled.append(context.job.id)
        await context.append_event({"type": "task.status", "message": "done"})

    runtime = BackgroundJobRuntime(repository, concurrency=1, poll_seconds=0.01)
    runtime.register("test", handler)
    try:
        job = await repository.enqueue(
            owner_user_id="user-a",
            job_id="job-1",
            kind="test",
            resource_type="test-resource",
            resource_id="resource-1",
        )
        await runtime.start()
        completed = await _wait_for_job(repository, "user-a", job.id, "succeeded")
        events = await repository.list_events(owner_user_id="user-a", job_id=job.id)
        await runtime.stop()

        recoverable = await repository.enqueue(
            owner_user_id="user-a",
            job_id="job-2",
            kind="test",
            resource_type="test-resource",
            resource_id="resource-2",
        )
        now = datetime.now(timezone.utc)
        first_claim = await repository.claim_next(
            worker_id="dead-worker",
            lease_expires_at=now - timedelta(seconds=1),
            now=now,
        )
        second_claim = await repository.claim_next(
            worker_id="replacement-worker",
            lease_expires_at=now + timedelta(seconds=31),
            now=now + timedelta(seconds=1),
        )

        cancelled = await repository.enqueue(
            owner_user_id="user-a",
            job_id="job-3",
            kind="test",
            resource_type="test-resource",
            resource_id="resource-3",
        )
        cancelled = await repository.request_cancel(owner_user_id="user-a", job_id=cancelled.id)
        retried = await repository.retry(
            owner_user_id="user-a",
            source_job_id="job-3",
            new_job_id="job-4",
        )
    finally:
        await runtime.stop()
        await engine.dispose()

    assert completed is not None and completed.attempt == 1
    assert handled == ["job-1"]
    assert [event.sequence for event in events] == [1]
    assert events[0].payload["message"] == "done"
    assert recoverable.status == "queued"
    assert first_claim is not None and first_claim.attempt == 1
    assert second_claim is not None and second_claim.id == "job-2"
    assert second_claim.attempt == 2
    assert cancelled is not None and cancelled.status == "cancelled"
    assert retried is not None and retried.retry_of_job_id == "job-3"
    assert await repository.get(owner_user_id="user-b", job_id="job-1") is None


@pytest.mark.asyncio
async def test_feedback_api_updates_targets_and_enforces_owner_scope(
    migrated_database_url: str,
) -> None:
    app = create_app(database_url=migrated_database_url, vector_store=FakeVectorStore())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        user_a = await _register(client, "feedback-a@example.com")
        user_b = await _register(client, "feedback-b@example.com")
        repositories = app.state.memory_repositories
        session = await repositories.chat.create_session(
            owner_user_id=user_a["user"]["id"],
            session_id="chat-feedback",
            title="Feedback",
        )
        await repositories.chat.append_message(
            owner_user_id=user_a["user"]["id"],
            message_id="message-feedback",
            session_id=session.id,
            role="assistant",
            content="Use the runbook.",
            metadata={"citations": [{"id": "citation-1", "title": "runbook"}]},
        )

        first = await client.post(
            "/feedback",
            headers=_headers(user_a),
            json={
                "targetType": "chat_message",
                "targetId": "message-feedback",
                "rating": "positive",
            },
        )
        updated = await client.post(
            "/feedback",
            headers=_headers(user_a),
            json={
                "targetType": "chat_message",
                "targetId": "message-feedback",
                "rating": "negative",
                "reason": "incomplete",
                "comment": "Missing rollback steps",
            },
        )
        citation = await client.post(
            "/feedback",
            headers=_headers(user_a),
            json={
                "targetType": "citation",
                "targetId": "message-feedback",
                "subjectId": "citation-1",
                "rating": "positive",
            },
        )
        forbidden = await client.post(
            "/feedback",
            headers=_headers(user_b),
            json={
                "targetType": "chat_message",
                "targetId": "message-feedback",
                "rating": "positive",
            },
        )
        listed = await client.get(
            "/feedback?targetType=chat_message&targetId=message-feedback",
            headers=_headers(user_a),
        )

    assert first.status_code == 200
    assert updated.json()["data"]["id"] == first.json()["data"]["id"]
    assert updated.json()["data"]["rating"] == "negative"
    assert citation.status_code == 200
    assert forbidden.status_code == 403
    assert len(listed.json()["data"]["items"]) == 1


@pytest.mark.asyncio
async def test_mcp_connection_api_validates_scope_and_persists_discovered_tools(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def discover(_self: LocalMcpClient) -> list[McpToolDefinition]:
        return [McpToolDefinition("SearchLog", "Search CLS logs", {"type": "object"}, "cls")]

    monkeypatch.setattr(LocalMcpClient, "discover_tools", discover)
    app = create_app(database_url=migrated_database_url, vector_store=FakeVectorStore())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        owner = await _register(client, "mcp-owner@example.com")
        other = await _register(client, "mcp-other@example.com")
        initial = await client.get("/mcp/connections", headers=_headers(owner))
        created = await client.post(
            "/mcp/connections",
            headers=_headers(owner),
            json={
                "name": "Local tools",
                "transport": "sse",
                "url": "http://127.0.0.1:3100/sse",
                "enabled": True,
                "timeoutSeconds": 10,
                "retries": 2,
            },
        )
        connection_id = created.json()["data"]["id"]
        checked = await client.post(
            f"/mcp/connections/{connection_id}:check",
            headers=_headers(owner),
        )
        forbidden = await client.delete(
            f"/mcp/connections/{connection_id}",
            headers=_headers(other),
        )
        invalid = await client.post(
            "/mcp/connections",
            headers=_headers(owner),
            json={
                "name": "Unsafe",
                "transport": "sse",
                "url": "file:///tmp/server",
                "enabled": True,
                "timeoutSeconds": 10,
                "retries": 0,
            },
        )

    assert initial.status_code == 200
    assert initial.json()["data"]["items"][0]["name"] == "腾讯云 CLS"
    assert created.status_code == 201
    assert checked.status_code == 200
    assert checked.json()["data"]["connection"]["lastCheck"]["toolCount"] == 1
    assert checked.json()["data"]["tools"][0]["name"] == "SearchLog"
    assert forbidden.status_code == 403
    assert invalid.status_code == 400


async def _wait_for_job(
    repository: SQLiteBackgroundJobRepository,
    owner_user_id: str,
    job_id: str,
    status: str,
) -> Any:
    for _ in range(100):
        current = await repository.get(owner_user_id=owner_user_id, job_id=job_id)
        if current is not None and current.status == status:
            return current
        await asyncio.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {status}")


async def _register(client: httpx.AsyncClient, email: str) -> dict[str, Any]:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "displayName": email.split("@", 1)[0],
            "password": "correct horse battery staple",
        },
    )
    return response.json()["data"]


def _headers(auth: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth['accessToken']}"}


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "extended-capabilities.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"
