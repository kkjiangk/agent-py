# Local infrastructure

Docker Compose provides **Kafka, Redis, etcd, MinIO, Milvus, Attu, and Alertmanager**. The backend, event worker, frontend, and official CLS MCP Server run as local application processes through the root launchers.

From the repository root:

```bash
docker compose -f infra/compose.yaml up -d --wait kafka redis etcd minio milvus attu alertmanager
docker compose -f infra/compose.yaml run --rm kafka-init
```

The initializer creates four `oncall.*.v1` topics for alerts, updates, dead letters, and remediation commands.

| Service | Address |
| --- | --- |
| Kafka | `127.0.0.1:9092` |
| Redis | `127.0.0.1:6379` |
| Milvus | `127.0.0.1:19530` |
| Milvus health/metrics | `http://127.0.0.1:9091` |
| Attu | `http://127.0.0.1:8001` |
| MinIO API / console | `http://127.0.0.1:9000` / `http://127.0.0.1:9001` |
| Alertmanager | `http://127.0.0.1:9093` |

Stop the stack while retaining named volumes:

```bash
docker compose -f infra/compose.yaml down
```

Removing volumes discards local infrastructure data. Compose does not include application services, upload documents, publish external logs, or provision a cloud monitoring stack. Local plaintext transport and development credentials target workstation use; production needs transport security and a production database/storage topology.

[Getting started](../docs/getting-started.md) covers launchers, [Configuration](../docs/configuration.md) covers Git-ignored private JSON, and [Real integration fixtures](../docs/tutorials/real-log-and-alert.md) covers explicitly invoked test uploads.
