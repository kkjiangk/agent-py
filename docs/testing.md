# Testing

## Fast regression checks

From the backend directory:

```bash
uv sync --frozen
uv run ruff check .
uv run pyright
uv run pytest
```

From the repository root:

```bash
npm ci
npm run contracts:typecheck
npm --workspace packages/api-contracts test
npm run frontend:typecheck
npm run frontend:test
npm run frontend:build
python3 scripts/check_frontend_bundle.py
npm audit --audit-level=moderate
npm run docs:build
```

Backend fixtures isolate project configuration from ignored developer credentials. Use targeted tests during implementation, then the checks appropriate to the changed boundary. Preserve strict typing and existing permission, envelope, and SSE assertions.

## Real Kafka and Redis integration

Start these local infrastructure services from the repository root:

```bash
docker compose -f infra/compose.yaml up -d --wait kafka redis
```

Then, from the backend directory:

```bash
uv run pytest integration_tests
```

The tests connect to real local services and create unique test topics, groups, and Redis keys. They clean only their own resources. They fail when the required dependencies are unavailable rather than silently skipping.

Covered cases include replay of a failed record after restarting a Kafka consumer, Redis busy/completed distinction, fencing of an expired owner, and creation of only one durable job on redelivery.

## Browser E2E

Install backend dependencies first so the browser harness can launch its virtual-environment interpreter. From the repository root:

```bash
npm exec --workspace apps/frontend playwright install chromium
npm run frontend:e2e
```

The harness launches a temporary SQLite backend on port 18080 and an isolated Vite server on 4173. It exercises real authentication, migrations, jobs, API ownership, document workflows, and SSE. Embedding, vector storage, alert listing, and diagnosis providers are explicit test-only adapters; no developer credentials or cloud model calls are used.

The three browser cases cover registration/session restoration/logout revocation with a cross-user rejection; upload/index/reload/preview/delete; and persisted diagnosis after browser disconnection, including a 390px layout check. Failure traces and screenshots are retained. The harness requires its two ports to be free.

## Container checks

From the repository root:

```bash
docker compose -f infra/compose.yaml config --quiet
docker build -f apps/backend/Dockerfile -t agent-py-backend:local .
docker build -f apps/frontend/Dockerfile -t agent-py-frontend:local .
```

## Recorded baseline

Local checks on 2026-10-04 passed 185 backend, 82 frontend, 24 contract, 3 real transport, and 3 Chromium tests. Strict static checks, frontend/documentation builds, both container builds, and a temporary backend-container migration/API-factory smoke check passed. npm audit reported zero known vulnerabilities at that time. Later dependency advisories or code changes require a fresh run.

CI defines equivalent categories and uploads browser evidence. Local results do not imply that a remote GitHub workflow has run. AWS operations and real model evaluations are separate, explicitly invoked workflows.
