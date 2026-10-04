from __future__ import annotations

import json
from pathlib import Path

import pytest

import super_ai.project_config as project_config

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def isolated_default_project_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep tests independent from ignored developer credentials and local endpoints."""
    config = json.loads(
        (REPO_ROOT / "config" / "project.template.json").read_text(encoding="utf-8")
    )
    config["llm"].update(
        {
            "apiKey": "sk-test-not-a-real-key",
            "chatModel": "qwen3.7-max",
            "embeddingModel": "text-embedding-v4",
            "modelCapabilities": {
                "qwen3.7-max": {"contextWindowTokens": 1_000_000}
            },
        }
    )
    config["clsLogUpload"].update(
        {"region": "ap-guangzhou", "logsetId": "test-logset", "topicId": "test-topic"}
    )
    config["backend"]["memoryDatabaseUrl"] = "sqlite+aiosqlite:///:memory:"
    config_path = tmp_path / "project.test.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(project_config, "DEFAULT_PROJECT_CONFIG_PATH", config_path)
    monkeypatch.setattr(
        project_config,
        "DEFAULT_USER_PROJECT_CONFIG_PATH",
        tmp_path / "user.project.test.json",
    )
