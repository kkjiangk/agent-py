"""Privacy-safe OpenTelemetry setup and span helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Status, StatusCode, Tracer

from super_ai.project_config import (
    ProjectConfigurationError,
    project_config_section,
    required_float,
    required_str,
)

_configuration_lock = Lock()
_configured = False


@dataclass(frozen=True, slots=True)
class TelemetrySettings:
    service_name: str
    otlp_http_endpoint: str | None
    sample_ratio: float


def load_telemetry_settings(*, config_path: Path | str | None = None) -> TelemetrySettings:
    section = project_config_section("telemetry", config_path=config_path)
    endpoint_value = section.get("otlpHttpEndpoint")
    endpoint = endpoint_value.strip() if isinstance(endpoint_value, str) else None
    sample_ratio = required_float(section, "sampleRatio")
    if not 0.0 <= sample_ratio <= 1.0:
        raise ValueError("telemetry.sampleRatio must be between 0 and 1.")
    return TelemetrySettings(
        service_name=required_str(section, "serviceName"),
        otlp_http_endpoint=endpoint or None,
        sample_ratio=sample_ratio,
    )


def configure_telemetry(*, config_path: Path | str | None = None) -> None:
    """Configure one process-wide provider; imports and config reads never connect externally."""
    global _configured
    with _configuration_lock:
        if _configured:
            return
        try:
            settings = load_telemetry_settings(config_path=config_path)
        except ProjectConfigurationError:
            settings = TelemetrySettings(
                service_name="agent-py-backend",
                otlp_http_endpoint=None,
                sample_ratio=1.0,
            )
        provider = TracerProvider(
            resource=Resource.create({"service.name": settings.service_name})
        )
        if settings.otlp_http_endpoint is not None:
            exporter = OTLPSpanExporter(endpoint=settings.otlp_http_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _configured = True


def get_tracer() -> Tracer:
    return trace.get_tracer("super_ai", "0.1.0")


def safe_span_attributes(attributes: Mapping[str, object]) -> dict[str, str | int | float | bool]:
    """Allow only low-cardinality scalar attributes; never serialize payloads or prompts."""
    safe: dict[str, str | int | float | bool] = {}
    for key, value in attributes.items():
        if isinstance(value, (str, int, float, bool)):
            safe[key] = value
    return safe


def record_span_error(span: Span, error: BaseException) -> None:
    """Record only the exception category to avoid leaking message contents."""
    span.set_attribute("error.type", error.__class__.__name__)
    span.set_status(Status(StatusCode.ERROR, error.__class__.__name__))
