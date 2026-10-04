from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from alembic import command
from alembic.config import Config

from super_ai.api.app import create_app
from super_ai.events import InMemoryEventPublisher
from super_ai.events.broker import PublishReceipt
from super_ai.events.config import load_event_ingestion_settings
from super_ai.memory.repositories import MemoryRepositories
from super_ai.remediation import RemediationApprovalService

PROJECT_TEMPLATE = Path(__file__).parents[3] / "config" / "project.template.json"


@pytest.mark.asyncio
async def test_high_risk_remediation_is_not_dispatched_until_owner_approves(
    migrated_database_url: str,
) -> None:
    publisher = InMemoryEventPublisher()
    app = create_app(
        database_url=migrated_database_url,
        project_config_path=PROJECT_TEMPLATE,
        alert_event_publisher=publisher,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = await _register(client, "approval-owner@example.com")
        other = await _register(client, "approval-other@example.com")
        repositories = cast(MemoryRepositories, app.state.memory_repositories)
        task = await repositories.diagnostics.create_task(
            owner_user_id=owner["user"]["id"],
            task_id="diagnostic-approval-1",
            status="succeeded",
            query="Investigate payment failure",
            input_payload={},
            result_payload={},
        )
        created = await client.post(
            f"/aiops/diagnostics/{task.id}/remediation-approvals",
            json={
                "toolName": "RestartService",
                "arguments": {"service": "payment-api"},
                "rationale": "Restart only after evidence review.",
                "riskLevel": "high",
            },
            headers=_auth_headers(owner),
        )
        approval_id = created.json()["data"]["id"]
        forbidden = await client.post(
            f"/aiops/remediation-approvals/{approval_id}:decide",
            json={"decision": "approved"},
            headers=_auth_headers(other),
        )
        approved = await client.post(
            f"/aiops/remediation-approvals/{approval_id}:decide",
            json={"decision": "approved", "decisionNote": "Reviewed logs and approved."},
            headers=_auth_headers(owner),
        )
        repeated = await client.post(
            f"/aiops/remediation-approvals/{approval_id}:decide",
            json={"decision": "approved"},
            headers=_auth_headers(owner),
        )

    assert created.status_code == 201
    assert created.json()["data"]["status"] == "pending"
    assert forbidden.status_code == 403
    assert approved.status_code == 200
    assert approved.json()["data"]["dispatchStatus"] == "dispatched"
    assert repeated.status_code == 200
    assert len(publisher.messages) == 1
    topic, key, value = publisher.messages[0]
    command = json.loads(value)
    assert topic == "oncall.remediation.commands.v1"
    assert key == approval_id
    assert command["approvalId"] == approval_id
    assert command["commandId"] == approval_id
    assert command["approvedByUserId"] == owner["user"]["id"]


@pytest.mark.asyncio
async def test_rejected_remediation_never_publishes_command(
    migrated_database_url: str,
) -> None:
    publisher = InMemoryEventPublisher()
    app = create_app(
        database_url=migrated_database_url,
        project_config_path=PROJECT_TEMPLATE,
        alert_event_publisher=publisher,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = await _register(client, "rejection-owner@example.com")
        repositories = cast(MemoryRepositories, app.state.memory_repositories)
        await repositories.diagnostics.create_task(
            owner_user_id=owner["user"]["id"],
            task_id="diagnostic-rejection-1",
            status="succeeded",
            query="Investigate checkout errors",
            input_payload={},
            result_payload={},
        )
        created = await client.post(
            "/aiops/diagnostics/diagnostic-rejection-1/remediation-approvals",
            json={
                "toolName": "RollbackDeployment",
                "arguments": {"service": "checkout-api"},
                "rationale": "Potential rollback candidate.",
                "riskLevel": "critical",
            },
            headers=_auth_headers(owner),
        )
        rejected = await client.post(
            f"/aiops/remediation-approvals/{created.json()['data']['id']}:decide",
            json={"decision": "rejected", "decisionNote": "Evidence is insufficient."},
            headers=_auth_headers(owner),
        )

    assert rejected.status_code == 200
    assert rejected.json()["data"]["status"] == "rejected"
    assert rejected.json()["data"]["dispatchStatus"] == "not_applicable"
    assert publisher.messages == []


@pytest.mark.asyncio
async def test_concurrent_dispatches_publish_only_one_command(
    migrated_database_url: str,
) -> None:
    class SlowPublisher(InMemoryEventPublisher):
        async def publish(self, *, topic: str, key: str, value: bytes) -> PublishReceipt:
            await asyncio.sleep(0.05)
            return await super().publish(topic=topic, key=key, value=value)

    publisher = SlowPublisher()
    app = create_app(database_url=migrated_database_url, project_config_path=PROJECT_TEMPLATE)
    repositories = cast(MemoryRepositories, app.state.memory_repositories)
    repo = repositories.remediation_approvals
    assert repo is not None
    await repositories.diagnostics.create_task(
        owner_user_id="user-a",
        task_id="diag-concurrent",
        status="succeeded",
        query="probe",
        input_payload={},
        result_payload={},
    )
    await repo.create(
        owner_user_id="user-a",
        approval_id="approval-concurrent",
        task_id="diag-concurrent",
        tool_name="RestartService",
        arguments={},
        rationale="reviewed",
        risk_level="high",
    )
    service = RemediationApprovalService(
        repository=repo,
        publisher=publisher,
        settings=load_event_ingestion_settings(config_path=PROJECT_TEMPLATE),
    )
    await asyncio.gather(
        *(
            service.decide(
                owner_user_id="user-a",
                approval_id="approval-concurrent",
                decision="approved",
                decision_note=None,
            )
            for _ in range(8)
        )
    )
    assert len(publisher.messages) == 1
    assert repositories.background_jobs is not None
    jobs = await repositories.background_jobs.list(owner_user_id="user-a")
    assert len(jobs) == 1
    assert jobs[0].kind == "remediation_dispatch"
    await app.state.memory_engine.dispose()


@pytest.mark.asyncio
async def test_durable_outbox_recovers_approval_after_app_restart(
    migrated_database_url: str,
) -> None:
    initial = create_app(database_url=migrated_database_url, project_config_path=PROJECT_TEMPLATE)
    repositories = cast(MemoryRepositories, initial.state.memory_repositories)
    repo = repositories.remediation_approvals
    assert repo is not None
    await repositories.diagnostics.create_task(
        owner_user_id="user-a",
        task_id="diag-recovery",
        status="succeeded",
        query="probe",
        input_payload={},
        result_payload={},
    )
    await repo.create(
        owner_user_id="user-a",
        approval_id="approval-recovery",
        task_id="diag-recovery",
        tool_name="RestartService",
        arguments={},
        rationale="reviewed",
        risk_level="high",
    )
    await repo.transition_pending(
        owner_user_id="user-a",
        approval_id="approval-recovery",
        status="approved",
        decided_by_user_id="user-a",
        decision_note=None,
    )
    await initial.state.memory_engine.dispose()
    publisher = InMemoryEventPublisher()
    recovered = create_app(
        database_url=migrated_database_url,
        project_config_path=PROJECT_TEMPLATE,
        alert_event_publisher=publisher,
    )
    async with recovered.router.lifespan_context(recovered):

        async def wait_for_dispatch() -> None:
            while not publisher.messages:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_dispatch(), 3)
    assert len(publisher.messages) == 1
    assert json.loads(publisher.messages[0][2])["commandId"] == "approval-recovery"


@pytest.mark.asyncio
async def test_stale_dispatcher_cannot_complete_new_lease(
    migrated_database_url: str,
) -> None:
    app = create_app(database_url=migrated_database_url, project_config_path=PROJECT_TEMPLATE)
    repositories = cast(MemoryRepositories, app.state.memory_repositories)
    repo = repositories.remediation_approvals
    assert repo is not None
    await repositories.diagnostics.create_task(
        owner_user_id="user-a",
        task_id="diag-fencing",
        status="succeeded",
        query="probe",
        input_payload={},
        result_payload={},
    )
    await repo.create(
        owner_user_id="user-a",
        approval_id="approval-fencing",
        task_id="diag-fencing",
        tool_name="RestartService",
        arguments={},
        rationale="reviewed",
        risk_level="high",
    )
    await repo.transition_pending(
        owner_user_id="user-a",
        approval_id="approval-fencing",
        status="approved",
        decided_by_user_id="user-a",
        decision_note=None,
    )
    now = datetime.now(timezone.utc)
    assert (
        await repo.claim_dispatch(
            owner_user_id="user-a",
            approval_id="approval-fencing",
            lease_owner="old",
            now=now,
            lease_expires_at=now + timedelta(seconds=1),
        )
        is not None
    )
    assert (
        await repo.claim_dispatch(
            owner_user_id="user-b",
            approval_id="approval-fencing",
            lease_owner="other",
            now=now,
            lease_expires_at=now + timedelta(seconds=1),
        )
        is None
    )
    assert (
        await repo.claim_dispatch(
            owner_user_id="user-a",
            approval_id="approval-fencing",
            lease_owner="new",
            now=now + timedelta(seconds=2),
            lease_expires_at=now + timedelta(seconds=62),
        )
        is not None
    )
    assert (
        await repo.finish_dispatch(
            owner_user_id="user-a",
            approval_id="approval-fencing",
            lease_owner="old",
            dispatch_status="dispatched",
            dispatch_error=None,
        )
        is None
    )
    updated = await repo.finish_dispatch(
        owner_user_id="user-a",
        approval_id="approval-fencing",
        lease_owner="new",
        dispatch_status="dispatched",
        dispatch_error=None,
    )
    assert updated is not None and updated.dispatch_status == "dispatched"
    await app.state.memory_engine.dispose()


@pytest.mark.asyncio
async def test_broker_failure_keeps_approved_outbox_for_retry(
    migrated_database_url: str,
) -> None:
    class FailOncePublisher(InMemoryEventPublisher):
        failed = False

        async def publish(self, *, topic: str, key: str, value: bytes) -> PublishReceipt:
            if not self.failed:
                self.failed = True
                raise RuntimeError("Injected broker failure")
            return await super().publish(topic=topic, key=key, value=value)

    publisher = FailOncePublisher()
    app = create_app(database_url=migrated_database_url, project_config_path=PROJECT_TEMPLATE)
    repositories = cast(MemoryRepositories, app.state.memory_repositories)
    repo = repositories.remediation_approvals
    assert repo is not None and repositories.background_jobs is not None
    try:
        await repositories.diagnostics.create_task(
            owner_user_id="owner",
            task_id="diag-retry",
            status="succeeded",
            query="test",
            input_payload={},
            result_payload={},
        )
        await repo.create(
            owner_user_id="owner",
            approval_id="approval-retry",
            task_id="diag-retry",
            tool_name="RestartService",
            arguments={},
            rationale="reviewed",
            risk_level="high",
        )
        service = RemediationApprovalService(
            repository=repo,
            publisher=publisher,
            settings=load_event_ingestion_settings(config_path=PROJECT_TEMPLATE),
        )
        with pytest.raises(RuntimeError, match="Injected"):
            await service.decide(
                owner_user_id="owner",
                approval_id="approval-retry",
                decision="approved",
                decision_note=None,
            )
        failed = await repo.get(owner_user_id="owner", approval_id="approval-retry")
        assert failed is not None and failed.status == "approved"
        assert failed.dispatch_status == "failed" and failed.dispatch_error == "RuntimeError"
        assert len(await repositories.background_jobs.list(owner_user_id="owner")) == 1
        recovered = await service.dispatch_approved(
            owner_user_id="owner", approval_id="approval-retry", require_completion=True
        )
        assert recovered.dispatch_status == "dispatched"
        assert len(publisher.messages) == 1
        assert json.loads(publisher.messages[0][2])["commandId"] == "approval-retry"
    finally:
        await app.state.memory_engine.dispose()


def _auth_headers(auth: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth['accessToken']}"}


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
    database_path = tmp_path / "remediation.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"
