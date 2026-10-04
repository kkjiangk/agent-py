# Deployment

The manual AWS workflow publishes an immutable SHA-tagged backend image and selects new ECS task-definition revisions for both API and event worker. It snapshots old revisions, verifies stable running tasks and their image names, performs a liveness smoke check, and attempts rollback on failure. The report is retained as a workflow artifact.

The root repository's AWS reference is `deploy/aws/README.md`. It lists the GitHub OIDC role, region, repository, cluster, API/worker service/container names, and health URL required by the workflow. The implementation entry point is `scripts/deploy_ecs.py`.

Apply Alembic migrations before updated code starts. Images contain templates rather than usable private credentials, so supply local-JSON configuration through a runtime provisioning process. Code rollback does not automatically downgrade schemas or delete recovery jobs.

SQLite and local plaintext Kafka/Redis remain the implemented environment. A production database adapter, transport authentication/TLS, validated multi-replica topology, SSE load-balancer sizing, and a deduplicating external remediation executor remain prerequisites. Fault-injection tests cover the release logic; they do not prove an actual cloud deployment.

See [Architecture](architecture.md), [Configuration](configuration.md), and [Testing](testing.md).
