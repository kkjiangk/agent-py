# Operations and monitoring

## Health and diagnostics

| Endpoint | Meaning |
| --- | --- |
| `/health` | API liveness and application version |
| `/ready` | SQLite, Milvus, model provider, and MCP readiness |
| `/config/check` | Configuration validation and dependency status |
| `/metrics` | Request counts, failures, and average latency in the API envelope |
| `/health/mcp` | Default MCP connection health |

`/metrics` is an application JSON endpoint, not a Prometheus exposition endpoint. OpenTelemetry spans cover Kafka, workflow/model activity, retrieval, and MCP tools. An empty OTLP HTTP endpoint disables external export; configure a collector explicitly if needed.

Request logs contain request IDs, route, status, and latency. Tool audits and diagnostic evidence persist in the user scope. Common credentials are redacted; summaries may still contain business information and need access control.

## Local configuration and logs

Copy `config/project.template.json` and `config/user.project.template.json` into the Git-ignored `config/project.json` and `config/user.project.json`. Model `apiKey`, CLS `secretId`/`secretKey`, region, logsetId, topicId, and demo password remain local. Review [Configuration](configuration.md) for all runtime sections.

The launchers place logs under the backend runtime directory:

- `backend-local.log`
- `aiops-event-worker-local.log`
- `cls-mcp-server-local.log`
- `frontend-local.log`

Use `docker compose -f infra/compose.yaml ps` to inspect infrastructure and `docker compose -f infra/compose.yaml logs kafka redis milvus` for container diagnostics. Do not paste unredacted private configuration into issues.

## Migrations and recovery

Apply `uv run alembic upgrade head` from the backend before starting updated API/worker code. The cross-platform launchers do this automatically. Revision `202610040001` adds fenced remediation dispatch leases and creates recovery jobs for older approved, unsent commands.

An exhausted event worker exits with the record uncommitted. Investigate dependencies or the failed event and restart the process; later successful messages cannot skip that record. Invalid input enters the sanitized DLQ only after broker acknowledgement.

Durable jobs recover expired execution leases and retry under their attempt policy. Remediation dispatch retries preserve commandId. If a job reaches its final failure state, inspect its owner-scoped error and use the existing job retry flow after resolving the cause.

## Common problems

- **API live but not ready:** inspect the dependency-specific readiness result rather than treating `/health` as a full integration check.
- **Milvus failures:** confirm etcd, MinIO, and Milvus health; match embedding and collection dimensions.
- **Model configuration failure:** check API key, selected model, and the matching modelCapabilities context-window profile.
- **CLS or MCP failure:** inspect the official CLI process, SSE address, actual enabled user connections, region, and topic access.
- **No active alerts:** check configured Prometheus/Alertmanager sources; fixture publishing is a separate action.
- **No knowledge matches:** check owner scope, successful indexing, source metadata, and the query before changing ranking.

[Real integration fixtures](tutorials/real-log-and-alert.md) describe explicit test-data uploads. Ordinary startup does not mutate a cloud log topic, upload documents, or run model evaluation.
