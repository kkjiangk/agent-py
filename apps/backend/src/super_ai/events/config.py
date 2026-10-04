"""JSON-backed Kafka and Redis settings for the incident event plane."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from super_ai.project_config import (
    ProjectConfigurationError,
    project_config_section,
    required_int,
    required_str,
)


@dataclass(frozen=True, slots=True)
class EventIngestionSettings:
    bootstrap_servers: str
    client_id: str
    consumer_group: str
    alerts_topic: str
    updates_topic: str
    dlq_topic: str
    remediation_topic: str
    redis_url: str
    event_lease_seconds: int
    event_retention_seconds: int


def load_event_ingestion_settings(
    *, config_path: Path | str | None = None
) -> EventIngestionSettings:
    """Load event-plane configuration without establishing external connections."""
    try:
        section = project_config_section("eventIngestion", config_path=config_path)
    except ProjectConfigurationError:
        section = {
            "bootstrapServers": "127.0.0.1:9092",
            "clientId": "agent-py-alert-gateway",
            "consumerGroup": "agent-py-aiops-workers-v1",
            "alertsTopic": "oncall.alerts.v1",
            "updatesTopic": "oncall.updates.v1",
            "dlqTopic": "oncall.dlq.v1",
            "remediationTopic": "oncall.remediation.commands.v1",
            "redisUrl": "redis://127.0.0.1:6379/0",
            "eventLeaseSeconds": 120,
            "eventRetentionSeconds": 604800,
        }
    settings = EventIngestionSettings(
        bootstrap_servers=required_str(section, "bootstrapServers"),
        client_id=required_str(section, "clientId"),
        consumer_group=required_str(section, "consumerGroup"),
        alerts_topic=required_str(section, "alertsTopic"),
        updates_topic=required_str(section, "updatesTopic"),
        dlq_topic=required_str(section, "dlqTopic"),
        remediation_topic=required_str(section, "remediationTopic"),
        redis_url=required_str(section, "redisUrl"),
        event_lease_seconds=required_int(section, "eventLeaseSeconds"),
        event_retention_seconds=required_int(section, "eventRetentionSeconds"),
    )
    if settings.event_lease_seconds < 5:
        raise ProjectConfigurationError("eventLeaseSeconds must be at least 5.")
    if settings.event_retention_seconds < settings.event_lease_seconds:
        raise ProjectConfigurationError(
            "eventRetentionSeconds must not be shorter than eventLeaseSeconds."
        )
    return settings
