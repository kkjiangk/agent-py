"""Application services joining alert ingestion to the durable diagnosis runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal, cast
from uuid import uuid4

from pydantic import ValidationError

from super_ai.events.broker import EventPublisher, PublishReceipt
from super_ai.events.config import EventIngestionSettings
from super_ai.events.models import (
    AlertEvent,
    BrokerAlertEnvelope,
    BrokerUpdateEvent,
    DeadLetterEvent,
)
from super_ai.events.state import EventStateStore
from super_ai.jobs import BackgroundJobRuntime
from super_ai.memory.repositories import DiagnosticTaskRecord, MemoryRepositories
from super_ai.telemetry import get_tracer, record_span_error, safe_span_attributes


@dataclass(frozen=True, slots=True)
class AcceptedAlert:
    task: DiagnosticTaskRecord
    receipt: PublishReceipt
    event_id: str
    incident_id: str


class AlertGatewayService:
    """Persist an accepted task and publish its owner-scoped event."""

    def __init__(
        self,
        *,
        repositories: MemoryRepositories,
        publisher: EventPublisher,
        settings: EventIngestionSettings,
    ) -> None:
        self._repositories = repositories
        self._publisher = publisher
        self._settings = settings

    async def accept(self, *, owner_user_id: str, event: AlertEvent) -> AcceptedAlert:
        diagnostic_id = deterministic_diagnostic_id(owner_user_id, event.event_id)
        task = await self._repositories.diagnostics.get_task(
            owner_user_id=owner_user_id,
            task_id=diagnostic_id,
        )
        alert_payload = _alert_payload(event)
        if task is None:
            task = await self._repositories.diagnostics.create_task(
                owner_user_id=owner_user_id,
                task_id=diagnostic_id,
                status="accepted",
                query=_diagnostic_query(event),
                input_payload={
                    "query": _diagnostic_query(event),
                    "alert": alert_payload,
                    "eventId": event.event_id,
                    "incidentId": event.incident_id,
                    "ingestion": "kafka",
                },
                result_payload={},
            )
        envelope = BrokerAlertEnvelope(
            eventId=event.event_id,
            incidentId=event.incident_id,
            diagnosticId=task.id,
            ownerUserId=owner_user_id,
            service=event.service,
            severity=event.severity,
            alertType=event.alert_type,
            occurredAt=event.occurred_at,
            payload=event.payload,
        )
        with get_tracer().start_as_current_span(
            "messaging.kafka.publish",
            attributes=safe_span_attributes(
                {
                    "messaging.destination.name": self._settings.alerts_topic,
                    "messaging.operation.type": "publish",
                    "event.id": event.event_id,
                    "incident.id": event.incident_id,
                    "diagnostic.id": task.id,
                }
            ),
        ) as span:
            try:
                receipt = await self._publisher.publish(
                    topic=self._settings.alerts_topic,
                    key=event.incident_id,
                    value=envelope.model_dump_json(by_alias=True).encode("utf-8"),
                )
            except Exception as exc:
                record_span_error(span, exc)
                await self._repositories.diagnostics.update_task(
                    owner_user_id=owner_user_id,
                    task_id=task.id,
                    status="failed",
                    result_payload={"failure": "Alert event could not be published."},
                    completed_at=datetime.now(timezone.utc),
                )
                raise
        return AcceptedAlert(
            task=task,
            receipt=receipt,
            event_id=event.event_id,
            incident_id=event.incident_id,
        )


class AlertEventProcessor:
    """Idempotently schedule broker events into the existing durable runtime."""

    def __init__(
        self,
        *,
        repositories: MemoryRepositories,
        runtime: BackgroundJobRuntime,
        publisher: EventPublisher,
        state_store: EventStateStore,
        settings: EventIngestionSettings,
    ) -> None:
        if repositories.background_jobs is None:
            raise ValueError("Background job repository is required.")
        self._repositories = repositories
        self._jobs = repositories.background_jobs
        self._runtime = runtime
        self._publisher = publisher
        self._state_store = state_store
        self._settings = settings

    async def process(self, raw_value: bytes) -> str:
        try:
            envelope = BrokerAlertEnvelope.model_validate_json(raw_value)
        except ValidationError as exc:
            await self._publish_dead_letter(raw_value, exc)
            return "dead-lettered"

        with get_tracer().start_as_current_span(
            "messaging.kafka.process",
            attributes=safe_span_attributes(
                {
                    "messaging.operation.type": "process",
                    "event.id": envelope.event_id,
                    "incident.id": envelope.incident_id,
                    "diagnostic.id": envelope.diagnostic_id,
                }
            ),
        ) as span:
            acquired = await self._state_store.acquire(
                owner_user_id=envelope.owner_user_id,
                event_id=envelope.event_id,
            )
            if acquired == "busy":
                raise EventLeaseBusyError("Event is still being scheduled by another worker.")
            if acquired == "completed":
                await self._publish_update(envelope, "duplicate")
                span.set_attribute("event.disposition", "duplicate")
                return "duplicate"
            try:
                disposition = await self._schedule(envelope)
                span.set_attribute("event.disposition", disposition)
                return disposition
            except Exception as exc:
                record_span_error(span, exc)
                await self._state_store.mark_failed(
                    owner_user_id=envelope.owner_user_id,
                    event_id=envelope.event_id,
                )
                raise

    async def _schedule(self, envelope: BrokerAlertEnvelope) -> str:
        task = await self._repositories.diagnostics.get_task(
            owner_user_id=envelope.owner_user_id,
            task_id=envelope.diagnostic_id,
        )
        if task is None:
            event = AlertEvent(
                eventId=envelope.event_id,
                incidentId=envelope.incident_id,
                service=envelope.service,
                severity=envelope.severity,
                alertType=envelope.alert_type,
                occurredAt=envelope.occurred_at,
                payload=envelope.payload,
            )
            task = await self._repositories.diagnostics.create_task(
                owner_user_id=envelope.owner_user_id,
                task_id=envelope.diagnostic_id,
                status="accepted",
                query=_diagnostic_query(event),
                input_payload={
                    "query": _diagnostic_query(event),
                    "alert": _alert_payload(event),
                    "eventId": event.event_id,
                    "incidentId": event.incident_id,
                    "ingestion": "kafka",
                },
                result_payload={},
            )
        job = await self._jobs.find_for_resource(
            owner_user_id=envelope.owner_user_id,
            resource_type="aiops_diagnostic",
            resource_id=task.id,
        )
        if job is None:
            await self._jobs.enqueue(
                owner_user_id=envelope.owner_user_id,
                job_id=f"job_{uuid4().hex}",
                kind="aiops_diagnosis",
                resource_type="aiops_diagnostic",
                resource_id=task.id,
                payload={
                    "diagnosticId": task.id,
                    "eventId": envelope.event_id,
                    "incidentId": envelope.incident_id,
                },
                max_attempts=3,
                timeout_seconds=1800,
            )
        await self._runtime.start()
        await self._publish_update(envelope, "scheduled")
        await self._state_store.mark_completed(
            owner_user_id=envelope.owner_user_id,
            event_id=envelope.event_id,
        )
        return "scheduled"

    async def _publish_update(
        self,
        envelope: BrokerAlertEnvelope,
        status: Literal["scheduled", "duplicate", "failed"],
    ) -> None:
        update = BrokerUpdateEvent(
            eventId=envelope.event_id,
            incidentId=envelope.incident_id,
            diagnosticId=envelope.diagnostic_id,
            status=status,
            occurredAt=datetime.now(timezone.utc),
        )
        await self._publisher.publish(
            topic=self._settings.updates_topic,
            key=envelope.incident_id,
            value=update.model_dump_json(by_alias=True).encode("utf-8"),
        )

    async def _publish_dead_letter(self, raw_value: bytes, error: ValidationError) -> None:
        event_id, incident_id = _safe_event_identity(raw_value)
        dead_letter = DeadLetterEvent(
            eventId=event_id,
            incidentId=incident_id,
            errorCategory=error.__class__.__name__,
            failedAt=datetime.now(timezone.utc),
        )
        await self._publisher.publish(
            topic=self._settings.dlq_topic,
            key=incident_id,
            value=dead_letter.model_dump_json(by_alias=True).encode("utf-8"),
        )


class EventLeaseBusyError(RuntimeError):
    """A live lease cannot be acknowledged as a completed duplicate."""


def deterministic_diagnostic_id(owner_user_id: str, event_id: str) -> str:
    digest = sha256(f"{owner_user_id}:{event_id}".encode()).hexdigest()[:32]
    return f"diagnostic_evt_{digest}"


def _diagnostic_query(event: AlertEvent) -> str:
    return (
        f"排查告警：{event.alert_type}，服务：{event.service}，级别：{event.severity}，"
        f"事件：{event.event_id}。"
    )


def _alert_payload(event: AlertEvent) -> dict[str, object]:
    return {
        "eventId": event.event_id,
        "incidentId": event.incident_id,
        "alertName": event.alert_type,
        "service": event.service,
        "severity": event.severity,
        "status": "active",
        "startsAt": event.occurred_at.isoformat(),
        "payload": event.payload,
        "alertSource": "event-gateway",
    }


def _safe_event_identity(raw_value: bytes) -> tuple[str, str]:
    try:
        payload = json.loads(raw_value)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "unknown", "unknown"
    if not isinstance(payload, dict):
        return "unknown", "unknown"
    typed_payload = cast(dict[str, object], payload)
    event_id = typed_payload.get("eventId")
    incident_id = typed_payload.get("incidentId")
    return (
        event_id if isinstance(event_id, str) and event_id else "unknown",
        incident_id if isinstance(incident_id, str) and incident_id else "unknown",
    )
