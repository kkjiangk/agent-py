from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

from super_ai.aiops.fixtures import (
    JAVA_ECOMMERCE_INCIDENTS,
    build_java_ecommerce_alert_payload,
    build_java_ecommerce_sop_documents,
    build_quant_alert_payload,
    generate_java_ecommerce_incident_logs,
    generate_quant_incident_logs,
)


def test_quant_alert_payload_matches_java_quant_service_incident() -> None:
    now = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)

    alert = build_quant_alert_payload(now)[0]
    labels = cast(dict[str, str], alert["labels"])
    annotations = cast(dict[str, str], alert["annotations"])

    assert labels["alertname"] == "QuantRiskPricingLatencyHigh"
    assert labels["service"] == "quant-risk-service"
    assert labels["environment"] == "test"
    assert annotations["sop"] == "ecommerce-quant-pricing-latency-sop"
    assert alert["startsAt"] == "2026-07-10T08:00:00Z"


def test_quant_logs_are_safe_structured_java_incident_evidence() -> None:
    now = datetime(2026, 7, 10, 8, 0, tzinfo=timezone.utc)

    logs = generate_quant_incident_logs(count=8, now=now)

    assert len(logs) == 8
    assert {log["service"] for log in logs} == {"quant-risk-service"}
    assert {log["logger"] for log in logs} == {"com.ecommerce.quant.risk.PricingEngine"}
    assert {log["sop"] for log in logs} == {"ecommerce-quant-pricing-latency-sop"}
    assert any(log["event"] == "quote_calculation_timeout" for log in logs)
    assert any(log["event"] == "pricing_engine_recovered" for log in logs)
    assert all("secret" not in " ".join(log.values()).lower() for log in logs)


def test_java_ecommerce_catalog_contains_ten_distinct_incidents_and_traces() -> None:
    assert len(JAVA_ECOMMERCE_INCIDENTS) == 10
    assert len({incident.incident_id for incident in JAVA_ECOMMERCE_INCIDENTS}) == 10
    assert len({incident.trace_id for incident in JAVA_ECOMMERCE_INCIDENTS}) == 10
    assert len({incident.service for incident in JAVA_ECOMMERCE_INCIDENTS}) == 10
    assert all(len(incident.trace_id) == 32 for incident in JAVA_ECOMMERCE_INCIDENTS)


def test_java_ecommerce_logs_alerts_and_sops_are_correlated() -> None:
    now = datetime(2026, 7, 11, 8, 0, tzinfo=timezone.utc)

    logs = generate_java_ecommerce_incident_logs(now=now)
    alerts = build_java_ecommerce_alert_payload(now)
    documents = build_java_ecommerce_sop_documents()

    assert len(logs) == len(alerts) == len(documents) == 10
    alerts_by_incident = {
        cast(dict[str, str], alert["labels"])["incident_id"]: alert
        for alert in alerts
    }
    documents_by_incident = {document.incident_id: document for document in documents}
    for log in logs:
        incident_id = log["incident_id"]
        alert = alerts_by_incident[incident_id]
        labels = cast(dict[str, str], alert["labels"])
        annotations = cast(dict[str, str], alert["annotations"])
        document = documents_by_incident[incident_id]

        assert labels["service"] == log["service"]
        assert log["host"] == f"{log['service']}-01"
        assert labels["alertname"] == log["alertname"]
        assert labels["environment"] == "test"
        assert labels["fixture"] == "java-ecommerce"
        assert annotations["trace_id"] == log["trace_id"]
        assert annotations["sop"] == log["sop"] == document.sop_id
        assert log["trace_id"] in document.content
        assert log["metric_name"] in document.content
        assert "## 排查步骤" in document.content
        assert "## 恢复步骤" in document.content
        assert "## 恢复验证" in document.content


def test_java_ecommerce_generated_data_contains_no_credentials() -> None:
    now = datetime(2026, 7, 11, 8, 0, tzinfo=timezone.utc)
    serialized = "\n".join(
        [
            *(" ".join(log.values()) for log in generate_java_ecommerce_incident_logs(now=now)),
            *(document.content for document in build_java_ecommerce_sop_documents()),
        ]
    ).lower()

    assert "secretid" not in serialized
    assert "secretkey" not in serialized
    assert "sk-" not in serialized
    assert "bearer " not in serialized
