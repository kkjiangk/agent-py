from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from alembic import command
from alembic.config import Config

from super_ai.api.app import create_app
from super_ai.events import (
    AlertEventProcessor,
    BrokerAlertEnvelope,
    InMemoryEventPublisher,
    InMemoryEventStateStore,
    load_event_ingestion_settings,
)
from super_ai.events.service import EventLeaseBusyError
from super_ai.events.state import event_state_keys
from super_ai.jobs import BackgroundJobRuntime
from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.sqlite import create_sqlite_memory_repositories

PROJECT_TEMPLATE = Path(__file__).parents[3] / "config" / "project.template.json"


class FakeRuntime:
    def __init__(self) -> None:
        self.start_count = 0

    async def start(self) -> None:
        self.start_count += 1


@pytest.mark.asyncio
async def test_authenticated_alert_gateway_publishes_owner_scoped_event_and_is_stable(
    migrated_database_url: str,
) -> None:
    publisher = InMemoryEventPublisher()
    transport = httpx.ASGITransport(
        app=create_app(
            database_url=migrated_database_url,
            project_config_path=PROJECT_TEMPLATE,
            alert_event_publisher=publisher,
        )
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        unauthenticated = await client.post("/aiops/alert-events", json=_alert_request())
        user = await _register(client, "event-owner@example.com")
        first = await client.post(
            "/aiops/alert-events",
            json={**_alert_request(), "ownerUserId": "forged-owner"},
            headers={"Authorization": f"Bearer {user['accessToken']}"},
        )
        second = await client.post(
            "/aiops/alert-events",
            json=_alert_request(),
            headers={"Authorization": f"Bearer {user['accessToken']}"},
        )

    assert unauthenticated.status_code == 401
    assert first.status_code == 202
    assert second.status_code == 202
    first_data = cast(dict[str, Any], first.json()["data"])
    second_data = cast(dict[str, Any], second.json()["data"])
    assert first_data["diagnostic"]["id"] == second_data["diagnostic"]["id"]
    assert first_data["broker"] == {"topic": "oncall.alerts.v1", "partition": 0, "offset": 0}
    assert publisher.messages[0][1] == "inc-20260824-001"
    envelope = json.loads(publisher.messages[0][2])
    assert envelope["ownerUserId"] == user["user"]["id"]
    assert envelope["ownerUserId"] != "forged-owner"


@pytest.mark.asyncio
async def test_event_processor_schedules_once_and_marks_duplicate(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        publisher = InMemoryEventPublisher()
        runtime = FakeRuntime()
        processor = AlertEventProcessor(
            repositories=repositories,
            runtime=cast(BackgroundJobRuntime, runtime),
            publisher=publisher,
            state_store=InMemoryEventStateStore(),
            settings=load_event_ingestion_settings(config_path=PROJECT_TEMPLATE),
        )
        envelope = BrokerAlertEnvelope(
            eventId="evt-0183",
            incidentId="inc-20260824-001",
            diagnosticId="diagnostic-event-1",
            ownerUserId="user-a",
            service="payment-api",
            severity="P1",
            alertType="high_error_rate",
            occurredAt=datetime.fromisoformat("2026-08-24T18:30:00+00:00"),
            payload={"errorRate": 0.32},
        )

        first = await processor.process(envelope.model_dump_json(by_alias=True).encode())
        second = await processor.process(envelope.model_dump_json(by_alias=True).encode())
        assert repositories.background_jobs is not None
        jobs = await repositories.background_jobs.list(owner_user_id="user-a")
        task = await repositories.diagnostics.get_task(
            owner_user_id="user-a",
            task_id="diagnostic-event-1",
        )
    finally:
        await engine.dispose()

    assert first == "scheduled"
    assert second == "duplicate"
    assert runtime.start_count == 1
    assert task is not None
    assert len(jobs) == 1
    assert [json.loads(item[2])["status"] for item in publisher.messages] == [
        "scheduled",
        "duplicate",
    ]


@pytest.mark.asyncio
async def test_invalid_broker_event_is_safely_dead_lettered(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        publisher = InMemoryEventPublisher()
        processor = AlertEventProcessor(
            repositories=repositories,
            runtime=cast(BackgroundJobRuntime, FakeRuntime()),
            publisher=publisher,
            state_store=InMemoryEventStateStore(),
            settings=load_event_ingestion_settings(config_path=PROJECT_TEMPLATE),
        )
        disposition = await processor.process(
            b'{"eventId":"bad-event","incidentId":"bad-incident","secret":"do-not-copy"}'
        )
    finally:
        await engine.dispose()

    assert disposition == "dead-lettered"
    assert publisher.messages[0][0] == "oncall.dlq.v1"
    dead_letter = json.loads(publisher.messages[0][2])
    assert dead_letter["eventId"] == "bad-event"
    assert "secret" not in dead_letter


def _alert_request() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "eventId": "evt-0183",
        "incidentId": "inc-20260824-001",
        "service": "payment-api",
        "severity": "P1",
        "alertType": "high_error_rate",
        "occurredAt": "2026-08-24T18:30:00Z",
        "payload": {"errorRate": 0.32, "region": "us-west-2"},
    }


@pytest.mark.asyncio
async def test_active_lease_is_not_acknowledged_as_completed_duplicate(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        state = InMemoryEventStateStore()
        assert await state.acquire(owner_user_id="user-a", event_id="evt-busy") == "acquired"
        publisher = InMemoryEventPublisher()
        processor = AlertEventProcessor(
            repositories=create_sqlite_memory_repositories(create_memory_session_factory(engine)),
            runtime=cast(BackgroundJobRuntime, FakeRuntime()), publisher=publisher,
            state_store=state,
            settings=load_event_ingestion_settings(config_path=PROJECT_TEMPLATE),
        )
        envelope = BrokerAlertEnvelope(
            eventId="evt-busy", incidentId="inc-busy", diagnosticId="diagnostic-busy",
            ownerUserId="user-a", service="payment-api", severity="P1",
            alertType="high_error_rate", occurredAt=datetime.fromisoformat(
                "2026-10-04T18:30:00+00:00"
            ), payload={},
        )
        with pytest.raises(EventLeaseBusyError):
            await processor.process(envelope.model_dump_json(by_alias=True).encode())
        assert publisher.messages == []
    finally:
        await engine.dispose()


def test_event_identity_keys_do_not_collide_on_separators() -> None:
    assert event_state_keys("a:b", "c") != event_state_keys("a_b", "c")
    assert event_state_keys("a", "b:c") != event_state_keys("a:b", "c")


async def _register(client: httpx.AsyncClient, email: str) -> dict[str, Any]:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "displayName": email.split("@")[0],
            "password": "correct horse battery staple",
        },
    )
    return cast(dict[str, Any], response.json()["data"])


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "event-ingestion.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"
