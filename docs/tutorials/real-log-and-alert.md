# Real logs, alerts, and runbooks

These explicit scripts publish synthetic incident data through actual CLS, Alertmanager, and application APIs. They are separate from normal startup and require a clearly selected test environment. They do not replay a production incident.

## Prerequisites

Start the application with configured model/CLS access and check `/ready`. Review `clsLogUpload`, `clsMcpServer`, `prometheusAlerts`, and `aiopsDemo` in private local JSON. Ensure the selected log topic, alert source, and demo account are appropriate for test data.

Each Java scenario correlates a log, active alert, SOP, and unique trace ID through `incident_id`, `service`, `alertname`, and `sop`. See [Scenario reference](../aiops/ecommerce-aiops-fixture.md).

## Publish test data

From the backend directory, first upload ten structured logs through the official CLS SDK:

```bash
uv run python scripts/generate_and_upload_cls_logs.py --profile java-ecommerce
```

Then publish ten local active alerts through the Alertmanager v2 API:

```bash
uv run python scripts/publish_java_ecommerce_alerts.py --profile java-ecommerce
```

Upload and index matching Markdown runbooks through the real backend API:

```bash
uv run python scripts/seed_java_ecommerce_aiops_sops.py --profile java-ecommerce
```

The seeding script uses the configured demo account and waits for successful indexing. These commands generate actual external/service writes; they are not part of unit or browser-test setup.

## Diagnose and verify

Log in to the workspace, refresh active alerts, select a Java fixture alert, and start a diagnosis. Review planner, executor, replanner, and report events.

A supported evidence chain should contain the selected alert, a corresponding knowledge citation, and CLS MCP `SearchLog` results with the same trace ID. Preserve tool failures and uncertainty rather than filling gaps with another scenario's evidence.

## Troubleshooting

- Confirm etcd, MinIO, and Milvus health if indexing fails.
- Check the official MCP process and configured SSE address for tool failures.
- Check region, topic permissions, and ingestion delay if CLS queries miss newly written logs.
- Check alert sources and configured local Alertmanager if no active alert appears.
- Verify owner scope and successful index jobs before adjusting a knowledge query.

Fixture scripts contain no real customer records. Do not add credentials, personal data, or production trading details to logs or reports. [Operations](../operations-and-monitoring.md) describes ordinary startup and recovery.
