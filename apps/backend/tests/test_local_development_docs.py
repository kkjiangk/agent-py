from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_root_readme_documents_local_startup_and_runtime_boundaries() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "## Local development" in readme
    assert "scripts/start-local.sh" in readme
    assert "scripts\\start-local.bat" in readme
    assert "Docker Compose provides" in readme
    assert "## Features" in readme
    for feature in (
        "Authentication and ownership",
        "Streaming chat",
        "Hybrid retrieval",
        "Incident diagnosis",
        "Reliable event delivery",
        "Remediation approval",
    ):
        assert feature in readme
    assert "single-node" in readme
    assert "at least once" in readme
    assert "commandId" in readme


def test_configuration_guide_covers_private_configuration_and_public_allowlist() -> None:
    guide = (REPO_ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")

    for expected in (
        "config/project.json",
        "config/user.project.json",
        "config/project.template.json",
        "config/user.project.template.json",
        "Git-ignored",
        "apiKey",
        "secretId",
        "secretKey",
        "logsetId",
        "topicId",
        "llm.modelCapabilities",
        "contextWindowTokens",
        "apiBaseUrl",
        "only setting emitted to browser code",
    ):
        assert expected in guide

    assert "config/project.compose.json" not in guide


def test_cross_platform_launchers_start_event_and_aiops_dependencies() -> None:
    shell_launcher = REPO_ROOT / "scripts" / "start-local.sh"
    windows_launcher = REPO_ROOT / "scripts" / "start-local.bat"

    shell = shell_launcher.read_text(encoding="utf-8")
    windows = windows_launcher.read_text(encoding="utf-8")

    for launcher in (shell, windows):
        normalized = launcher.replace("\\\n", " ")
        assert "kafka redis etcd minio milvus attu alertmanager" in normalized
        assert "docker compose -f infra/compose.yaml run --rm kafka-init" in normalized
        assert normalized.index("up -d") < normalized.index("run --rm kafka-init")
    assert "uvicorn super_ai.api.app:create_app" in shell
    assert "cls-mcp-server" in shell
    assert "npm run dev" in shell
    assert "super_ai.events.worker" in shell
    assert "</dev/null" in shell
    assert "uvicorn super_ai.api.app:create_app" in windows
    assert "cls-mcp-server" in windows
    assert "npm run dev" in windows
    assert "super_ai.events.worker" in windows


def test_posix_launcher_has_valid_shell_syntax() -> None:
    shell_launcher = REPO_ROOT / "scripts" / "start-local.sh"

    result = subprocess.run(
        ["bash", "-n", str(shell_launcher)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_getting_started_covers_both_platforms_and_real_fixture_workflows() -> None:
    guide = (REPO_ROOT / "docs" / "getting-started.md").read_text(encoding="utf-8")
    for command in (
        "./scripts/start-local.sh",
        "scripts\\start-local.bat",
        "cls-mcp-server",
        "uv sync --frozen",
        "uv run alembic upgrade head",
        "docker compose -f infra/compose.yaml up -d --wait "
        "kafka redis etcd minio milvus attu alertmanager",
        "docker compose -f infra/compose.yaml run --rm kafka-init",
    ):
        assert command in guide
    assert guide.index("up -d --wait") < guide.index("run --rm kafka-init")

    tutorial = (REPO_ROOT / "docs" / "tutorials" / "real-log-and-alert.md").read_text(
        encoding="utf-8"
    )
    for expected in (
        "generate_and_upload_cls_logs.py",
        "publish_java_ecommerce_alerts.py",
        "seed_java_ecommerce_aiops_sops.py",
        "SearchLog",
    ):
        assert expected in tutorial
