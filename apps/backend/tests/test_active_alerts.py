from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from alembic import command
from alembic.config import Config

from super_ai.alerts import (
    ActiveAlert,
    AggregatedAlertProvider,
    AlertmanagerAlertProvider,
    AlertProviderError,
    PrometheusAlertProvider,
)
from super_ai.api.app import create_app


class FakeAlertProvider:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error

    async def list_active_alerts(self) -> list[ActiveAlert]:
        if self.error is not None:
            raise self.error
        return [
            ActiveAlert(
                id="fingerprint-checkout-latency",
                source="test-provider",
                alert_name="CheckoutLatencyHigh",
                service="checkout",
                severity="critical",
                status="active",
                starts_at="2026-07-10T08:00:00Z",
                summary="Checkout latency is above the SLO.",
                labels={"alertname": "CheckoutLatencyHigh", "service": "checkout"},
                annotations={"summary": "Checkout latency is above the SLO."},
                context={"fingerprint": "fingerprint-checkout-latency"},
            )
        ]


@pytest.mark.asyncio
async def test_alertmanager_provider_normalizes_active_v2_alerts() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json=[
                {
                    "fingerprint": "fingerprint-checkout-latency",
                    "labels": {
                        "alertname": "CheckoutLatencyHigh",
                        "service": "checkout",
                        "severity": "critical",
                    },
                    "annotations": {"summary": "Checkout latency is above the SLO."},
                    "startsAt": "2026-07-10T08:00:00Z",
                    "status": {"state": "active"},
                },
                {
                    "fingerprint": "silenced-alert",
                    "labels": {"alertname": "SilencedAlert"},
                    "annotations": {},
                    "startsAt": "2026-07-10T08:00:00Z",
                    "status": {"state": "suppressed"},
                },
            ],
        )
    )
    provider = AlertmanagerAlertProvider(
        alerts_api="http://alertmanager.test/api/v2/alerts",
        timeout_seconds=3,
        transport=transport,
    )

    alerts = await provider.list_active_alerts()

    assert len(alerts) == 1
    assert alerts[0].alert_name == "CheckoutLatencyHigh"
    assert alerts[0].service == "checkout"
    assert alerts[0].context["fingerprint"] == "fingerprint-checkout-latency"


@pytest.mark.asyncio
async def test_aggregated_provider_keeps_prometheus_source_and_tolerates_one_failed_source(
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "prometheus.test":
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "alerts": [
                            {
                                "activeAt": "2026-07-10T08:00:00Z",
                                "annotations": {"summary": "Quote latency is too high."},
                                "labels": {
                                    "alertname": "QuantRiskPricingLatencyHigh",
                                    "service": "quant-risk-service",
                                    "severity": "critical",
                                },
                                "state": "firing",
                                "value": "1",
                            }
                        ]
                    },
                },
            )
        return httpx.Response(503)

    transport = httpx.MockTransport(respond)
    provider = AggregatedAlertProvider(
        providers=(
            PrometheusAlertProvider(
                source_id="external-prometheus",
                alerts_api="https://prometheus.test/api/v1/alerts",
                timeout_seconds=3,
                transport=transport,
            ),
            AlertmanagerAlertProvider(
                source_id="local-alertmanager",
                alerts_api="http://alertmanager.test/api/v2/alerts",
                timeout_seconds=3,
                transport=transport,
            ),
        )
    )

    alerts = await provider.list_active_alerts()

    assert len(alerts) == 1
    assert alerts[0].source == "external-prometheus"
    assert alerts[0].status == "active"
    assert alerts[0].context["alertSource"] == "external-prometheus"
    assert alerts[0].context["alertSourceType"] == "prometheus-v1"


@pytest.mark.asyncio
async def test_active_alert_endpoint_requires_auth_and_surfaces_provider_failure(
    migrated_database_url: str,
) -> None:
    transport = httpx.ASGITransport(
        app=create_app(
            database_url=migrated_database_url,
            alert_provider=FakeAlertProvider(error=AlertProviderError("unavailable")),
        )
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        unauthenticated = await client.get("/aiops/alerts/active")
        user = await _register(client, "alerts-owner@example.com")
        unavailable = await client.get(
            "/aiops/alerts/active",
            headers={"Authorization": f"Bearer {user['accessToken']}"},
        )

    assert unauthenticated.status_code == 401
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "SYSTEM_UNAVAILABLE"
    assert "unavailable" not in unavailable.text


@pytest.mark.asyncio
async def test_active_alert_endpoint_returns_normalized_alerts_for_authenticated_user(
    migrated_database_url: str,
) -> None:
    transport = httpx.ASGITransport(
        app=create_app(database_url=migrated_database_url, alert_provider=FakeAlertProvider())
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user = await _register(client, "alerts-list@example.com")
        response = await client.get(
            "/aiops/alerts/active",
            headers={"Authorization": f"Bearer {user['accessToken']}"},
        )

    assert response.status_code == 200
    payload = cast(dict[str, Any], response.json()["data"])
    assert payload["items"][0]["alertName"] == "CheckoutLatencyHigh"
    assert payload["items"][0]["source"] == "test-provider"
    assert payload["items"][0]["context"]["fingerprint"] == "fingerprint-checkout-latency"


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
    database_path = tmp_path / "active-alerts.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"
