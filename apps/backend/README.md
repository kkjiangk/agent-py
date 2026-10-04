# Backend

Python 3.10+, FastAPI, Pydantic, SQLAlchemy/Alembic, LangChain/LangGraph, and uv. Application modules live under `src/super_ai` and use `from super_ai...` imports.

## Run and verify

From this directory, after completing local JSON configuration:

```bash
uv sync --frozen
uv run alembic upgrade head
uv run uvicorn super_ai.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

In a separate terminal, start event consumption:

```bash
uv run python -m super_ai.events.worker
```

Checks:

```bash
uv run ruff check .
uv run pyright
uv run pytest
# Requires actual local Kafka and Redis:
uv run pytest integration_tests
```

## Code boundaries

- `api`: factory, typed request schemas, authentication router, envelopes, SSE, and resource assembly.
- `auth`: Argon2 passwords, hashed bearer sessions, and token revocation.
- `memory`: repository protocols, SQLite implementations, and persisted domain records.
- `jobs`: existing durable runtime for indexing, diagnosis, and remediation dispatch.
- `events`: versioned envelopes, Kafka adapters, Redis leases/checkpoints, gateway, and worker.
- `retrieval`: scoped vector/lexical recall, reusable BM25L index/cache, RRF, and reranking.
- `chat`, `aiops`, `llm`, `mcp_client`: actual configured agents, tools, and external providers.
- `deployment`, `evaluation_runner`: explicit release operations and API-driven evaluation.

The default SQLite URL points to `var/memory.sqlite3`. Apply migrations before updated code starts; revision `202610040001` adds dispatch leases and backfills approved unsent commands. Modules must not establish external connections at import time.

See the root [README](../../README.md), [Configuration](../../docs/configuration.md), [Architecture](../../docs/architecture.md), and [Testing](../../docs/testing.md) for complete instructions and boundaries.
