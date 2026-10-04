@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0.."
cd /d "%ROOT_DIR%"

where docker >nul 2>nul || (echo 缺少必需命令：docker & exit /b 1)
where npm >nul 2>nul || (echo 缺少必需命令：npm & exit /b 1)
where uv >nul 2>nul || (echo 缺少必需命令：uv & exit /b 1)
where cls-mcp-server >nul 2>nul || (echo 缺少必需命令：cls-mcp-server & exit /b 1)

for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "function Merge-Config($base,$override){ foreach($p in $override.PSObject.Properties){ if($null -ne $base.($p.Name) -and $base.($p.Name) -is [pscustomobject] -and $p.Value -is [pscustomobject]){ Merge-Config $base.($p.Name) $p.Value } else { $base ^| Add-Member -NotePropertyName $p.Name -NotePropertyValue $p.Value -Force } }; $base }; $config = Get-Content -Raw 'config/project.json' ^| ConvertFrom-Json; if(Test-Path 'config/user.project.json'){ $user = Get-Content -Raw 'config/user.project.json' ^| ConvertFrom-Json; $config = Merge-Config $config $user }; Write-Output ('TRANSPORT=' + $config.clsMcpServer.transport); Write-Output ('PORT=' + $config.clsMcpServer.port); Write-Output ('TENCENTCLOUD_SECRET_ID=' + $config.clsMcpServer.secretId); Write-Output ('TENCENTCLOUD_SECRET_KEY=' + $config.clsMcpServer.secretKey); Write-Output ('TZ=' + $config.clsMcpServer.timezone)"`) do set "%%A"

docker compose -f infra/compose.yaml up -d kafka redis etcd minio milvus attu alertmanager
docker compose -f infra/compose.yaml run --rm kafka-init
if errorlevel 1 exit /b 1

pushd apps\backend
if not exist var mkdir var
uv sync
if errorlevel 1 exit /b 1
uv run alembic upgrade head
if errorlevel 1 exit /b 1
start "Agent Py CLS MCP" /D "%CD%" cmd /c "cls-mcp-server > var\cls-mcp-server-local.log 2>&1"
start "Agent Py Backend" /D "%CD%" cmd /c "uv run uvicorn super_ai.api.app:create_app --factory --host 127.0.0.1 --port 8000 > var\backend-local.log 2>&1"
start "Agent Py AIOps Event Worker" /D "%CD%" cmd /c "uv run python -m super_ai.events.worker > var\aiops-event-worker-local.log 2>&1"
popd

pushd apps\frontend
if not exist node_modules npm install
if errorlevel 1 exit /b 1
start "Agent Py Frontend" /D "%CD%" cmd /c "npm run dev -- --host 127.0.0.1 > ..\backend\var\frontend-local.log 2>&1"
popd

echo 前端：     http://127.0.0.1:5173
echo 后端：     http://127.0.0.1:8000
echo MCP SSE：  http://127.0.0.1:%PORT%/sse
echo Kafka：    127.0.0.1:9092
echo Redis：    127.0.0.1:6379
echo 本地日志： apps\backend\var
