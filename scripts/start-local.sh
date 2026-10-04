#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/apps/backend"
FRONTEND_DIR="$ROOT_DIR/apps/frontend"
RUNTIME_DIR="$BACKEND_DIR/var"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf '缺少必需命令：%s\n' "$1" >&2
    exit 1
  fi
}

port_is_open() {
  python3 - "$1" <<'PY'
import socket
import sys

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
    connection.settimeout(0.5)
    raise SystemExit(0 if connection.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
}

require_command docker
require_command npm
require_command python3

if command -v uv >/dev/null 2>&1; then
  UV_BIN="$(command -v uv)"
elif [ -x "$ROOT_DIR/.venv/bin/uv" ]; then
  UV_BIN="$ROOT_DIR/.venv/bin/uv"
else
  printf '%s\n' '缺少 uv。请先执行 `brew install uv`，或在仓库 .venv/bin/uv 中安装 uv。' >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  printf '%s\n' 'Docker daemon 未运行。请先启动 Docker Desktop，等待引擎就绪后重新执行本脚本。' >&2
  exit 1
fi

cd "$ROOT_DIR"
mkdir -p "$RUNTIME_DIR"

eval "$(python3 - "$ROOT_DIR/config/project.json" "$ROOT_DIR/config/user.project.json" <<'PY'
import json
import shlex
import sys
from pathlib import Path

def deep_merge(base, override):
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = value
    return merged

config = json.load(open(sys.argv[1], encoding="utf-8"))
override_path = Path(sys.argv[2])
if override_path.exists():
    config = deep_merge(config, json.load(open(override_path, encoding="utf-8")))
mcp = config["clsMcpServer"]
for name, value in {
    "CLS_MCP_SERVER_VERSION": config["docker"]["clsMcpServerVersion"],
    "TRANSPORT": mcp["transport"],
    "PORT": str(mcp["port"]),
    "TENCENTCLOUD_SECRET_ID": mcp["secretId"],
    "TENCENTCLOUD_SECRET_KEY": mcp["secretKey"],
    "TZ": mcp["timezone"],
}.items():
    print(f"export {name}={shlex.quote(value)}")
PY
)"

if command -v cls-mcp-server >/dev/null 2>&1; then
  MCP_COMMAND=("$(command -v cls-mcp-server)")
else
  MCP_COMMAND=(npx --yes "cls-mcp-server@$CLS_MCP_SERVER_VERSION")
  printf '未发现全局 cls-mcp-server，将通过 npx 使用固定版本 %s。\n' \
    "$CLS_MCP_SERVER_VERSION"
fi

docker compose -f infra/compose.yaml up -d \
  kafka redis etcd minio milvus attu alertmanager
docker compose -f infra/compose.yaml run --rm kafka-init

(
  cd "$BACKEND_DIR"
  "$UV_BIN" sync
  "$UV_BIN" run alembic upgrade head
)

if ! port_is_open "$PORT"; then
  (
    cd "$BACKEND_DIR"
    nohup "${MCP_COMMAND[@]}" </dev/null > "$RUNTIME_DIR/cls-mcp-server-local.log" 2>&1 &
  )
fi

if ! port_is_open 8000; then
  (
    cd "$BACKEND_DIR"
    nohup "$UV_BIN" run uvicorn super_ai.api.app:create_app --factory --host 127.0.0.1 --port 8000 \
      </dev/null > "$RUNTIME_DIR/backend-local.log" 2>&1 &
  )
fi

if ! pgrep -f "python -m super_ai.events.worker" >/dev/null 2>&1; then
  (
    cd "$BACKEND_DIR"
    nohup "$UV_BIN" run python -m super_ai.events.worker \
      </dev/null > "$RUNTIME_DIR/aiops-event-worker-local.log" 2>&1 &
  )
fi

if ! port_is_open 5173; then
  (
    cd "$FRONTEND_DIR"
    if [ ! -d node_modules ]; then
      npm install
    fi
    nohup npm run dev -- --host 127.0.0.1 </dev/null > "$RUNTIME_DIR/frontend-local.log" 2>&1 &
  )
fi

printf '前端：     http://127.0.0.1:5173\n'
printf '后端：     http://127.0.0.1:8000\n'
printf 'MCP SSE：  http://127.0.0.1:%s/sse\n' "$PORT"
printf 'Kafka：    127.0.0.1:9092\n'
printf 'Redis：    127.0.0.1:6379\n'
printf '本地日志： %s\n' "$RUNTIME_DIR"
