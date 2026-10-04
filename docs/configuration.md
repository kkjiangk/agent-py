# Configuration

## Sources and overrides

The application loads two local JSON files:

- `config/project.json`: base configuration copied from `config/project.template.json`.
- `config/user.project.json`: overrides copied from `config/user.project.template.json`.

Objects are merged recursively; override values replace base values. Application code does not use `.env` or machine environment variables as project configuration sources. The launcher forwards selected JSON CLS settings into the official CLI process. GitHub deployment workflow variables are CI inputs rather than application configuration.

Both private JSON files are Git-ignored. Commit only the templates. Never put a usable API key, secretId, secretKey, logsetId, topicId, or demo password in checked-in examples.

## Runtime sections

| Section | Fields and purpose |
| --- | --- |
| `backend` | `memoryDatabaseUrl`, host, and port; manual commands and the launcher choose their listening addresses |
| `frontend` | `apiBaseUrl` is the only setting emitted to browser code by the public-config plugin |
| `llm` | `apiKey`, `baseUrl`, `chatModel`, `embeddingModel`, dimensions, reranker, timeouts, and retries |
| `vectorStore` | Milvus URI, collection name, vectorDimension, HNSW/COSINE settings, and search parameters |
| `clsMcpServer` | transport, port, secretId, secretKey, and timezone for the official local CLI |
| `mcp` | default CLS SSE URL, timeouts, and retries |
| `prometheusAlerts` | actual Prometheus v1 or Alertmanager v2 sources and optional authentication |
| `eventIngestion` | Kafka addresses/topics/group, Redis URL, lease duration, and completion retention |
| `telemetry` | service name, optional OTLP HTTP endpoint, and sample ratio |
| `clsLogUpload` | test-upload region, endpoint, logsetId, topicId, and bounded record counts |
| `aiopsDemo` | account and endpoints used only by explicitly invoked fixture scripts |

## Model capability profile

The selected `chatModel` must have a corresponding entry in `llm.modelCapabilities` with a positive `contextWindowTokens` value. Use the capability of the actual deployed model. Changing model names requires updating that key; the backend rejects a missing profile.

Embedding dimensions must match the Milvus collection schema. A new dimension requires a matching collection rather than silently inserting incompatible vectors. Templates select no actual credential, and copying them alone does not establish external readiness.

## Browser and container configuration

Vite reads local JSON in Node and emits only `frontend.apiBaseUrl`. User overrides still apply to that public URL. If private JSON is absent, it uses templates; browser E2E mode uses its isolated local proxy. Build-time API URL changes require rebuilding frontend assets. The checked-in Nginx file is a static SPA server; it does not replace this API configuration.

Docker images copy credential-free JSON templates. Supply actual private configuration through an appropriate runtime mount or secret-provisioning process. The repository does not contain an automatic Secrets Manager configuration adapter.

## Checks

`/config/check` validates runtime configuration and checks dependencies; `/ready` checks dependency readiness. These endpoints expose status rather than a credential dump. `python3 scripts/check_frontend_bundle.py` scans built assets for configured credential values, while a separate canary build test verifies the public allowlist. The scan is supplemental, not a substitute for the allowlist.
