"""Real Prometheus and Alertmanager-compatible active-alert providers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import httpx

from super_ai.project_config import (
    ProjectConfigurationError,
    project_config_section,
    required_float,
    required_str,
)


class AlertProviderError(RuntimeError):
    """Raised when the configured external alert provider cannot be queried safely."""


@dataclass(frozen=True, slots=True)
class ActiveAlert:
    """A normalized active alert with preserved provider provenance."""

    id: str
    source: str
    alert_name: str
    service: str
    severity: str
    status: str
    starts_at: str
    summary: str
    labels: dict[str, str]
    annotations: dict[str, str]
    context: dict[str, object]


class ActiveAlertProvider(Protocol):
    """Boundary for reading active external alerts."""

    async def list_active_alerts(self) -> list[ActiveAlert]:
        """Return current active alerts from the configured external service."""
        ...


@dataclass(frozen=True, slots=True)
class AlertmanagerAlertProvider:
    """Read one Alertmanager v2 alerts endpoint on demand."""

    alerts_api: str
    timeout_seconds: float
    source_id: str = "alertmanager"
    username: str | None = None
    password: str | None = None
    transport: httpx.AsyncBaseTransport | None = None

    async def list_active_alerts(self) -> list[ActiveAlert]:
        payload = await _read_json(
            alerts_api=self.alerts_api,
            timeout_seconds=self.timeout_seconds,
            username=self.username,
            password=self.password,
            transport=self.transport,
        )
        if not isinstance(payload, list):
            raise AlertProviderError("The configured alert provider returned an invalid response.")
        return _normalized_alerts(
            cast(list[object], payload),
            source_id=self.source_id,
            source_type="alertmanager-v2",
        )


@dataclass(frozen=True, slots=True)
class PrometheusAlertProvider:
    """Read one Prometheus v1 alerts endpoint on demand."""

    alerts_api: str
    timeout_seconds: float
    source_id: str = "prometheus"
    username: str | None = None
    password: str | None = None
    transport: httpx.AsyncBaseTransport | None = None

    async def list_active_alerts(self) -> list[ActiveAlert]:
        payload = await _read_json(
            alerts_api=self.alerts_api,
            timeout_seconds=self.timeout_seconds,
            username=self.username,
            password=self.password,
            transport=self.transport,
        )
        root = _object_mapping(payload)
        data = _object_mapping(root.get("data"))
        raw_alerts = data.get("alerts")
        if root.get("status") != "success" or not isinstance(raw_alerts, list):
            raise AlertProviderError("The configured alert provider returned an invalid response.")
        return _normalized_alerts(
            cast(list[object], raw_alerts),
            source_id=self.source_id,
            source_type="prometheus-v1",
        )


@dataclass(frozen=True, slots=True)
class AggregatedAlertProvider:
    """Return valid alerts from all configured external providers."""

    providers: tuple[ActiveAlertProvider, ...]

    async def list_active_alerts(self) -> list[ActiveAlert]:
        results: list[ActiveAlert] = []
        successful_sources = 0
        for provider in self.providers:
            try:
                results.extend(await provider.list_active_alerts())
            except AlertProviderError:
                continue
            successful_sources += 1
        if successful_sources == 0:
            raise AlertProviderError("The configured alert provider is unavailable.")
        return sorted(results, key=lambda alert: (alert.source, alert.starts_at, alert.id))


def build_alertmanager_alert_provider(
    *,
    config_path: Path | str | None = None,
) -> ActiveAlertProvider:
    """Build configured real alert readers from tracked project configuration."""
    try:
        config = project_config_section("prometheusAlerts", config_path=config_path)
        timeout_seconds = required_float(config, "timeoutSeconds")
        sources = config.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ProjectConfigurationError("At least one alert source must be configured.")
        configured_sources = cast(list[object], sources)
        providers = tuple(
            _build_alert_provider(source, timeout_seconds=timeout_seconds)
            for source in configured_sources
        )
    except ProjectConfigurationError as exc:
        raise AlertProviderError("The configured alert provider is invalid.") from exc
    return AggregatedAlertProvider(providers=providers)


def _build_alert_provider(source: object, *, timeout_seconds: float) -> ActiveAlertProvider:
    if not isinstance(source, Mapping):
        raise ProjectConfigurationError("Alert source must be an object.")
    source_mapping = cast(Mapping[str, object], source)
    source_id = required_str(source_mapping, "id")
    source_type = required_str(source_mapping, "type")
    alerts_api = required_str(source_mapping, "alertsApi")
    username = _optional_str(source_mapping, "username")
    password = _optional_str(source_mapping, "password")
    if (username is None) != (password is None):
        raise ProjectConfigurationError(
            "Alert source credentials must include username and password."
        )
    if source_type == "alertmanager-v2":
        return AlertmanagerAlertProvider(
            alerts_api=alerts_api,
            timeout_seconds=timeout_seconds,
            source_id=source_id,
            username=username,
            password=password,
        )
    if source_type == "prometheus-v1":
        return PrometheusAlertProvider(
            alerts_api=alerts_api,
            timeout_seconds=timeout_seconds,
            source_id=source_id,
            username=username,
            password=password,
        )
    raise ProjectConfigurationError(f"Unsupported alert source type: {source_type}")


async def _read_json(
    *,
    alerts_api: str,
    timeout_seconds: float,
    username: str | None,
    password: str | None,
    transport: httpx.AsyncBaseTransport | None,
) -> object:
    auth = (
        httpx.BasicAuth(username, password)
        if username is not None and password is not None
        else None
    )
    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
            transport=transport,
            auth=auth,
        ) as client:
            response = await client.get(alerts_api)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AlertProviderError("The configured alert provider is unavailable.") from exc


def _normalized_alerts(
    raw_alerts: list[object],
    *,
    source_id: str,
    source_type: str,
) -> list[ActiveAlert]:
    alerts: list[ActiveAlert] = []
    for item in raw_alerts:
        if not isinstance(item, dict):
            raise AlertProviderError("The configured alert provider returned an invalid response.")
        alert = _normalize_alert(
            cast(dict[str, object], item), source_id=source_id, source_type=source_type
        )
        if alert is not None:
            alerts.append(alert)
    return alerts


def _normalize_alert(
    raw_alert: Mapping[str, object],
    *,
    source_id: str,
    source_type: str,
) -> ActiveAlert | None:
    status = _string_mapping(raw_alert.get("status"))
    state = status.get("state", _string_value(raw_alert.get("state"), ""))
    if state not in {"active", "firing"}:
        return None

    labels = _string_mapping(raw_alert.get("labels"))
    annotations = _string_mapping(raw_alert.get("annotations"))
    alert_name = labels.get("alertname", "Unknown alert")
    service = labels.get("service", labels.get("job", "Unspecified service"))
    severity = labels.get("severity", "unknown")
    starts_at = _string_value(raw_alert.get("startsAt"), "") or _string_value(
        raw_alert.get("activeAt"), ""
    )
    fingerprint = _string_value(raw_alert.get("fingerprint"), "")
    alert_id = fingerprint or f"{source_id}:{alert_name}:{service}:{starts_at}"
    summary = annotations.get("summary", annotations.get("description", "No summary provided."))
    context = dict(raw_alert)
    context["alertSource"] = source_id
    context["alertSourceType"] = source_type

    return ActiveAlert(
        id=alert_id,
        source=source_id,
        alert_name=alert_name,
        service=service,
        severity=severity,
        status="active",
        starts_at=starts_at,
        summary=summary,
        labels=labels,
        annotations=annotations,
        context=context,
    )


def _object_mapping(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in cast(dict[object, object], value).items()
        if isinstance(key, str) and isinstance(item, str)
    }


def _string_value(value: object, fallback: str) -> str:
    return value if isinstance(value, str) else fallback


def _optional_str(source: Mapping[str, object], key: str) -> str | None:
    value = source.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ProjectConfigurationError(f"Alert source field must be a non-empty string: {key}")
    return value.strip()
