# Getting started

## Prerequisites

Install Python 3.10 or newer, uv, Node.js 22 or newer, and Docker with the Compose plugin. Confirm `uv`, `npm`, and `docker` are available and the Docker engine is running. The backend uses uv; the frontend and shared contracts use npm workspaces.

For CLS integration, install the official `cls-mcp-server` CLI. The POSIX launcher can fall back to the version pinned in the JSON template through npx; the Windows launcher requires the CLI on PATH.

## Configure and launch

From the repository root on macOS/Linux:

```bash
npm ci
cp config/project.template.json config/project.json
cp config/user.project.template.json config/user.project.json
# Fill private values and model settings in the copied JSON files.
./scripts/start-local.sh
```

On Windows Command Prompt:

```bat
npm ci
copy config\project.template.json config\project.json
copy config\user.project.template.json config\user.project.json
scripts\start-local.bat
```

Review [Configuration](configuration.md) before launching. Templates contain no usable model API key or CLS credentials. The launcher creates runtime logs under the backend's `var` directory, initializes Kafka topics, installs backend dependencies, applies Alembic migrations, and starts application processes.

The frontend listens on port 5173, the API on 8000, and the template CLS MCP server on 3000. POSIX launchers reuse already-open application ports; inspect existing processes and logs if the browser shows an older version.

## Manual startup

Infrastructure, from the repository root:

```bash
docker compose -f infra/compose.yaml up -d --wait kafka redis etcd minio milvus attu alertmanager
docker compose -f infra/compose.yaml run --rm kafka-init
```

Backend, from its directory:

```bash
cd apps/backend
uv sync --frozen
uv run alembic upgrade head
uv run uvicorn super_ai.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

In another terminal, from the backend directory:

```bash
uv run python -m super_ai.events.worker
```

Start the official CLS MCP server with the credentials and transport from local JSON, then start the frontend from the repository root:

```bash
npm run frontend:dev
```

Use the launcher for forwarding JSON credentials into the official MCP process. Application code continues to load project configuration from JSON.

## First use

Register a user in the workspace. Upload a Markdown runbook or PDF and wait for successful indexing. Chat can select knowledge tools and enabled MCP connections. The diagnosis page can start a query or use a configured active alert.

Check `/health` for liveness, `/ready` for dependency readiness, and `/config/check` for configuration and dependency checks. A healthy `/health` response alone does not prove model, MCP, or vector readiness.

## Stop and reset

Stop application processes separately from the Compose stack. Infrastructure shutdown preserves named volumes:

```bash
docker compose -f infra/compose.yaml down
```

The backend's SQLite data and application logs are separate from Compose volumes. Removing volumes or the SQLite database discards local data. Startup does not automatically upload external logs, seed knowledge, or run evaluations.
