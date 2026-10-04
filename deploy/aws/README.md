# AWS deployment reference

The release tooling deploys API and event-worker services from the same immutable backend image. API uses the default Uvicorn command behind a load balancer; worker overrides its command to `python -m super_ai.events.worker` and exposes no public port.

## Current scope

This is a deployment reference and release-control implementation. SQLite remains the implemented persistence adapter. Multi-replica production operation requires a suitable database adapter, secure broker connections, and an explicit scheduling/storage topology. Both application lifespans currently start the durable job runtime.

Plan MSK or another supported Kafka endpoint, Redis, Milvus, model/MCP access, application storage, and optional OTLP telemetry before deploying. A managed service name alone does not make the current plaintext Kafka/Redis client configuration production-ready.

## GitHub environment

The manual `.github/workflows/deploy-aws.yml` workflow uses GitHub OIDC. Configure these inputs in the target environment:

| Input | Type | Purpose |
| --- | --- | --- |
| `AWS_DEPLOY_ROLE_ARN` | Secret | Assumed deployment role |
| `AWS_REGION` | Variable | AWS region |
| `ECR_BACKEND_REPOSITORY` | Variable | Backend image repository |
| `ECS_CLUSTER` | Variable | Cluster containing both services |
| `ECS_BACKEND_SERVICE` | Variable | API service name |
| `ECS_WORKER_SERVICE` | Variable | Event-worker service name |
| `ECS_API_CONTAINER` | Variable | API container name in its task definition |
| `ECS_WORKER_CONTAINER` | Variable | Worker container name in its task definition |
| `API_HEALTH_URL` | Variable | HTTPS application `/health` URL |

The deployment role needs narrowly scoped ECR publishing, ECS service/task-definition describe/register/update/list operations and applicable `iam:PassRole` permissions. The CLI waiter uses describe permissions rather than a separate IAM wait action. Enable ECR tag immutability if using SHA tags as immutable version identifiers.

## Release behavior

1. Build and push the backend image using the Git commit SHA as its tag.
2. Snapshot previous task-definition revisions for both services.
3. Register definitions that reference the selected image for the matching containers.
4. Update API and worker explicitly and enable the deployment circuit breaker.
5. Wait for service stability and verify running task revisions and image names.
6. Run the application health smoke check.
7. If any release step fails after an attempted update, try restoring previous revisions and record rollback failures.

The workflow uploads `deployment-report.json` even on failure. A `/health` smoke check verifies application liveness; dependency readiness and operational load still need additional production checks. Release and rollback branches have local fault-injection coverage; an actual AWS release is a separate manual operation.

## Configuration and migrations

Images contain credential-free configuration templates. Supply actual private JSON through an appropriate runtime mount or provisioning flow. The application does not automatically read Secrets Manager or environment-based project configuration.

Apply `alembic upgrade head` through the backend environment before new code starts. Revision `202610040001` adds nullable dispatch lease columns and backfills approved unsent remediation jobs. Code rollback retains these schema additions; the release script does not automatically downgrade the database or delete outbox data.

## Remaining production work

- PostgreSQL or another production repository adapter and validated job-leasing behavior.
- Kafka TLS/SASL and Redis authentication/TLS support.
- Load-balancer timeouts and reconnect behavior for persisted SSE.
- Capacity measurements, durable shared storage, autoscaling, and dependency readiness checks.
- A remediation executor that deduplicates `commandId` before side effects.

See [Architecture](../../docs/architecture.md), [Engineering decisions](../../docs/engineering-quality.md), and [Testing](../../docs/testing.md).
