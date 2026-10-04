"""Small in-process observability primitives for local application operations."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True, slots=True)
class RequestMetricsSnapshot:
    request_count: int
    failure_count: int
    total_latency_ms: float


class RequestMetrics:
    def __init__(self) -> None:
        self._failure_count = 0
        self._lock = Lock()
        self._request_count = 0
        self._total_latency_ms = 0.0

    def record(self, *, latency_ms: float, status_code: int) -> None:
        with self._lock:
            self._request_count += 1
            self._total_latency_ms += latency_ms
            if status_code >= 500:
                self._failure_count += 1

    def snapshot(self) -> RequestMetricsSnapshot:
        with self._lock:
            return RequestMetricsSnapshot(
                request_count=self._request_count,
                failure_count=self._failure_count,
                total_latency_ms=self._total_latency_ms,
            )
