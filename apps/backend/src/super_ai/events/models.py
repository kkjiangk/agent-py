"""Versioned event contracts for asynchronous AIOps ingestion."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AlertSeverity = Literal[
    "P1", "P2", "P3", "P4", "critical", "high", "medium", "low"
]


class AlertEvent(BaseModel):
    """Public alert payload accepted by the authenticated gateway."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    event_id: str = Field(alias="eventId", min_length=1, max_length=160)
    incident_id: str = Field(alias="incidentId", min_length=1, max_length=160)
    service: str = Field(min_length=1, max_length=160)
    severity: AlertSeverity
    alert_type: str = Field(alias="alertType", min_length=1, max_length=160)
    occurred_at: datetime = Field(alias="occurredAt")
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_id", "incident_id", "service", "alert_type")
    @classmethod
    def strip_identifiers(cls, value: str) -> str:
        return value.strip()


class BrokerAlertEnvelope(BaseModel):
    """Internal owner-scoped event transported through Kafka."""

    model_config = ConfigDict(populate_by_name=True)

    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    event_id: str = Field(alias="eventId")
    incident_id: str = Field(alias="incidentId")
    diagnostic_id: str = Field(alias="diagnosticId")
    owner_user_id: str = Field(alias="ownerUserId")
    service: str
    severity: AlertSeverity
    alert_type: str = Field(alias="alertType")
    occurred_at: datetime = Field(alias="occurredAt")
    payload: dict[str, Any]


class BrokerUpdateEvent(BaseModel):
    """Backend progress event published for downstream gateways and audit consumers."""

    model_config = ConfigDict(populate_by_name=True)

    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    event_id: str = Field(alias="eventId")
    incident_id: str = Field(alias="incidentId")
    diagnostic_id: str = Field(alias="diagnosticId")
    status: Literal["scheduled", "duplicate", "failed"]
    occurred_at: datetime = Field(alias="occurredAt")


class DeadLetterEvent(BaseModel):
    """Sanitized dead-letter record; raw secrets and exception text are excluded."""

    model_config = ConfigDict(populate_by_name=True)

    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    event_id: str = Field(alias="eventId")
    incident_id: str = Field(alias="incidentId")
    error_category: str = Field(alias="errorCategory")
    failed_at: datetime = Field(alias="failedAt")


class BrokerRemediationCommand(BaseModel):
    """Stable command identity for downstream side-effect deduplication."""

    model_config = ConfigDict(populate_by_name=True)

    schema_version: Literal[1] = Field(default=1, alias="schemaVersion")
    command_id: str = Field(alias="commandId")
    approval_id: str = Field(alias="approvalId")
    diagnostic_id: str = Field(alias="diagnosticId")
    owner_user_id: str = Field(alias="ownerUserId")
    tool_name: str = Field(alias="toolName")
    arguments: dict[str, object]
    risk_level: Literal["low", "medium", "high", "critical"] = Field(alias="riskLevel")
    approved_by_user_id: str | None = Field(alias="approvedByUserId")
    approved_at: str | None = Field(alias="approvedAt")
