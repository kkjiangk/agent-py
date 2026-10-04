from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.sqlite import SQLiteKnowledgeDocumentRepository


@pytest.mark.asyncio
async def test_lexical_revision_is_owner_scoped_and_changes_on_index_update_or_delete(
    tmp_path: Path,
) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'revision.sqlite3'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    await asyncio.to_thread(command.upgrade, config, "head")
    engine = create_memory_engine(url)
    repository = SQLiteKnowledgeDocumentRepository(create_memory_session_factory(engine))
    try:
        empty = await repository.lexical_revision(owner_user_id="a", knowledge_base_ids=["kb"])
        for owner in ["a", "b"]:
            await repository.create_document(
                owner_user_id=owner,
                document_id=f"doc-{owner}",
                knowledge_base_id="kb",
                filename="test.md",
                size_bytes=1,
                mime_type="text/markdown",
                content_hash=owner,
            )
        original = await repository.lexical_revision(owner_user_id="a", knowledge_base_ids=["kb"])
        assert original != empty
        await repository.mark_document_deleted(
            owner_user_id="b", knowledge_base_id="kb", document_id="doc-b"
        )
        assert original == await repository.lexical_revision(
            owner_user_id="a", knowledge_base_ids=["kb"]
        )
        await repository.update_index_status(
            owner_user_id="a", knowledge_base_id="kb", document_id="doc-a", index_status="indexed"
        )
        assert original != await repository.lexical_revision(
            owner_user_id="a", knowledge_base_ids=["kb"]
        )
        await repository.mark_document_deleted(
            owner_user_id="a", knowledge_base_id="kb", document_id="doc-a"
        )
        assert empty == await repository.lexical_revision(
            owner_user_id="a", knowledge_base_ids=["kb"]
        )
    finally:
        await engine.dispose()
