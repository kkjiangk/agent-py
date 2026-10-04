"""Isolated browser-test server: real auth/SQLite/jobs/SSE, explicit test-only providers."""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import cast
from uuid import uuid4

import uvicorn
from alembic import command
from alembic.config import Config

from super_ai.alerts import ActiveAlert
from super_ai.api.app import create_app
from super_ai.memory.repositories import DiagnosticTaskRecord, MemoryRepositories
from super_ai.vector_store import MilvusHealthCheckResult, VectorChunkRecord


class BrowserEmbedding:
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


class BrowserVectors:
    def __init__(self) -> None:
        self.chunks: list[VectorChunkRecord] = []

    def health_check(self) -> MilvusHealthCheckResult:
        return MilvusHealthCheckResult(
            ok=True,
            uri="test-only://in-memory",
            collection_name="browser-fixture",
            latency_ms=0,
        )

    def initialize(self) -> None:
        return None

    def insert_chunks(self, chunks: Sequence[VectorChunkRecord]) -> None:
        self.chunks.extend(chunks)

    def delete_document_chunks(
        self, *, tenant_id: str, knowledge_base_id: str, document_id: str
    ) -> None:
        self.chunks = [
            chunk
            for chunk in self.chunks
            if not (
                chunk.tenant_id == tenant_id
                and chunk.knowledge_base_id == knowledge_base_id
                and chunk.document_id == document_id
            )
        ]


class BrowserAlerts:
    async def list_active_alerts(self) -> list[ActiveAlert]:
        return []


class BrowserDiagnostic:
    def __init__(self, repositories: MemoryRepositories) -> None:
        self.repositories = repositories

    async def stream(
        self, *, task: DiagnosticTaskRecord, accessible_knowledge_base_ids: Sequence[str]
    ) -> AsyncIterator[dict[str, object]]:
        del accessible_knowledge_base_ids
        await self.repositories.diagnostics.update_task(
            owner_user_id=task.owner_user_id,
            task_id=task.id,
            status="running",
        )
        base: dict[str, object] = {
            "channel": "aiops",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        yield {
            **base,
            "id": uuid4().hex,
            "type": "task.status",
            "task": {"id": task.id, "status": "running"},
        }
        await asyncio.sleep(1)
        content = "# Browser E2E fixture report\n\nPersisted report survives browser disconnection."
        report = await self.repositories.diagnostics.add_report(
            owner_user_id=task.owner_user_id,
            report_id=f"report_{uuid4().hex}",
            task_id=task.id,
            title="Browser E2E fixture report",
            content=content,
            payload={"format": "markdown"},
        )
        await self.repositories.diagnostics.update_task(
            owner_user_id=task.owner_user_id,
            task_id=task.id,
            status="succeeded",
            completed_at=datetime.now(timezone.utc),
        )
        yield {
            **base,
            "id": uuid4().hex,
            "type": "report",
            "report": {
                "id": report.id,
                "title": report.title,
                "content": content,
                "format": "markdown",
            },
        }
        yield {**base, "id": uuid4().hex, "type": "complete"}


def main() -> None:
    repo = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix="agent-py-browser-e2e-") as directory:
        config: dict[str, object] = json.loads(
            (repo / "config/project.template.json").read_text(encoding="utf-8")
        )
        config_path = Path(directory) / "project.json"
        llm = cast(dict[str, object], config["llm"])
        llm["chatModel"] = "test-only-chat"
        llm["modelCapabilities"] = {"test-only-chat": {"contextWindowTokens": 32000}}
        llm["embeddingModel"] = "test-only-embedding"
        llm["apiKey"] = "sk-browser-fixture-not-a-real-key"
        database_url = f"sqlite+aiosqlite:///{directory}/browser.sqlite3"
        cast(dict[str, object], config["backend"])["memoryDatabaseUrl"] = database_url
        config_path.write_text(json.dumps(config), encoding="utf-8")
        migration = Config(str(repo / "apps/backend/alembic.ini"))
        migration.set_main_option("script_location", str(repo / "apps/backend/alembic"))
        migration.set_main_option("sqlalchemy.url", database_url)
        command.upgrade(migration, "head")
        app = create_app(
            database_url=database_url,
            project_config_path=config_path,
            vector_store=BrowserVectors(),
            embedding_model=BrowserEmbedding(),
            alert_provider=BrowserAlerts(),
        )
        app.state.aiops_diagnostic_runner = BrowserDiagnostic(
            cast(MemoryRepositories, app.state.memory_repositories)
        )
        uvicorn.run(app, host="127.0.0.1", port=18080, log_level="warning")


if __name__ == "__main__":
    main()
