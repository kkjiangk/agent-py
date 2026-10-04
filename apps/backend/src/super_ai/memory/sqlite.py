"""SQLite-backed memory repository implementations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, TypeVar, cast
from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy import delete as sql_delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from super_ai.memory.models import (
    AgentToolCallAuditModel,
    ChatMessageModel,
    ChatSessionModel,
    DiagnosticCaseModel,
    DiagnosticEvidenceModel,
    DiagnosticReportModel,
    DiagnosticStepModel,
    DiagnosticTaskModel,
    DocumentIndexTaskModel,
    GraphCheckpointModel,
    KnowledgeDocumentModel,
    ReportEvidenceLinkModel,
    ToolCallAuditModel,
    UserChatConfigurationModel,
    UserChatPromptModel,
    UserChatSkillModel,
    utc_now,
)
from super_ai.memory.repositories import (
    AgentToolCallAuditRecord,
    ChatMessageRecord,
    ChatSessionRecord,
    DiagnosticCaseRecord,
    DiagnosticEvidenceRecord,
    DiagnosticReportRecord,
    DiagnosticStepRecord,
    DiagnosticTaskRecord,
    DocumentIndexTaskRecord,
    GraphCheckpointRecord,
    JsonDict,
    KnowledgeDocumentRecord,
    MemoryRepositories,
    ReportEvidenceLinkRecord,
    TenantScopeError,
    TimeRangeFilter,
    ToolCallAuditRecord,
    UserChatConfigurationRecord,
    UserChatPromptRecord,
    UserChatSkillRecord,
)

ModelT = TypeVar("ModelT")
_UNSET = object()


class SQLiteChatMemoryRepository:
    """SQLite implementation of chat memory persistence."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_session(
        self,
        *,
        owner_user_id: str,
        session_id: str,
        title: str | None = None,
        created_at: datetime | None = None,
    ) -> ChatSessionRecord:
        timestamp = created_at or utc_now()
        row = ChatSessionModel(
            id=session_id,
            owner_user_id=owner_user_id,
            title=title,
            created_at=timestamp,
            updated_at=timestamp,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
        return _chat_session_record(row)

    async def get_session(
        self,
        *,
        owner_user_id: str,
        session_id: str,
    ) -> ChatSessionRecord | None:
        stmt = select(ChatSessionModel).where(
            ChatSessionModel.id == session_id,
            ChatSessionModel.owner_user_id == owner_user_id,
        )
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).one_or_none()
        return _chat_session_record(row) if row is not None else None

    async def update_session_title(
        self,
        *,
        owner_user_id: str,
        session_id: str,
        title: str,
        updated_at: datetime | None = None,
    ) -> ChatSessionRecord | None:
        timestamp = updated_at or utc_now()
        async with self._session_factory() as session:
            row = await _find_chat_session(session, owner_user_id, session_id)
            if row is None:
                return None
            row.title = title
            row.updated_at = timestamp
            await session.commit()
        return _chat_session_record(row)

    async def update_memory_state(
        self,
        *,
        owner_user_id: str,
        session_id: str,
        memory_mode: str | None = None,
        memory_summary: str | None = None,
        compacted_message_count: int | None = None,
        context_tokens: int | None = None,
        last_compacted_at: datetime | None = None,
        clear_compaction: bool = False,
        updated_at: datetime | None = None,
    ) -> ChatSessionRecord | None:
        timestamp = updated_at or utc_now()
        async with self._session_factory() as session:
            row = await _find_chat_session(session, owner_user_id, session_id)
            if row is None:
                return None
            if memory_mode is not None:
                row.memory_mode = memory_mode
            if clear_compaction:
                row.memory_summary = None
                row.compacted_message_count = 0
                row.context_tokens = 0
                row.last_compacted_at = None
            else:
                if memory_summary is not None:
                    row.memory_summary = memory_summary
                if compacted_message_count is not None:
                    row.compacted_message_count = compacted_message_count
                if context_tokens is not None:
                    row.context_tokens = context_tokens
                if last_compacted_at is not None:
                    row.last_compacted_at = last_compacted_at
            row.updated_at = timestamp
            await session.commit()
        return _chat_session_record(row)

    async def list_sessions(
        self,
        *,
        owner_user_id: str,
        time_range: TimeRangeFilter | None = None,
    ) -> list[ChatSessionRecord]:
        stmt = select(ChatSessionModel).where(ChatSessionModel.owner_user_id == owner_user_id)
        stmt = _apply_time_range(stmt, ChatSessionModel.created_at, time_range)
        stmt = stmt.order_by(ChatSessionModel.updated_at.desc(), ChatSessionModel.id.asc())
        async with self._session_factory() as session:
            rows = list((await session.scalars(stmt)).all())
        return [_chat_session_record(row) for row in rows]

    async def append_message(
        self,
        *,
        owner_user_id: str,
        message_id: str,
        session_id: str,
        role: str,
        content: str,
        metadata: JsonDict | None = None,
        created_at: datetime | None = None,
    ) -> ChatMessageRecord:
        timestamp = created_at or utc_now()
        row = ChatMessageModel(
            id=message_id,
            owner_user_id=owner_user_id,
            session_id=session_id,
            role=role,
            content=content,
            metadata_json=metadata or {},
            created_at=timestamp,
        )
        async with self._session_factory() as session:
            parent = await _require_chat_session(session, owner_user_id, session_id)
            parent.updated_at = timestamp
            session.add(row)
            await session.commit()
        return _chat_message_record(row)

    async def clear_messages(
        self,
        *,
        owner_user_id: str,
        session_id: str,
        updated_at: datetime | None = None,
    ) -> int:
        timestamp = updated_at or utc_now()
        async with self._session_factory() as session:
            parent = await _find_chat_session(session, owner_user_id, session_id)
            if parent is None:
                return 0
            message_ids = list(
                (
                    await session.scalars(
                        select(ChatMessageModel.id).where(
                            ChatMessageModel.owner_user_id == owner_user_id,
                            ChatMessageModel.session_id == session_id,
                        )
                    )
                ).all()
            )
            await session.execute(
                sql_delete(ChatMessageModel).where(
                    ChatMessageModel.owner_user_id == owner_user_id,
                    ChatMessageModel.session_id == session_id,
                )
            )
            parent.updated_at = timestamp
            parent.memory_summary = None
            parent.compacted_message_count = 0
            parent.context_tokens = 0
            parent.last_compacted_at = None
            await session.commit()
        return len(message_ids)

    async def delete_session(
        self,
        *,
        owner_user_id: str,
        session_id: str,
    ) -> bool:
        async with self._session_factory() as session:
            row = await _find_chat_session(session, owner_user_id, session_id)
            if row is None:
                return False
            await session.execute(
                sql_delete(ChatMessageModel).where(
                    ChatMessageModel.owner_user_id == owner_user_id,
                    ChatMessageModel.session_id == session_id,
                )
            )
            await session.delete(row)
            await session.commit()
        return True

    async def list_messages(
        self,
        *,
        owner_user_id: str,
        session_id: str,
        time_range: TimeRangeFilter | None = None,
    ) -> list[ChatMessageRecord]:
        stmt = select(ChatMessageModel).where(
            ChatMessageModel.owner_user_id == owner_user_id,
            ChatMessageModel.session_id == session_id,
        )
        stmt = _apply_time_range(stmt, ChatMessageModel.created_at, time_range)
        stmt = stmt.order_by(ChatMessageModel.created_at.asc(), ChatMessageModel.id.asc())
        async with self._session_factory() as session:
            rows = list((await session.scalars(stmt)).all())
        return [_chat_message_record(row) for row in rows]

    async def get_message(
        self,
        *,
        owner_user_id: str,
        message_id: str,
    ) -> ChatMessageRecord | None:
        stmt = select(ChatMessageModel).where(
            ChatMessageModel.id == message_id,
            ChatMessageModel.owner_user_id == owner_user_id,
        )
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).one_or_none()
        return _chat_message_record(row) if row is not None else None


class SQLiteUserChatConfigurationRepository:
    """SQLite owner-scoped chat assembly persistence."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_or_create(
        self, *, owner_user_id: str, system_prompt_id: str, skill_ids: list[str]
    ) -> UserChatConfigurationRecord:
        async with self._session_factory() as session:
            row = await session.get(UserChatConfigurationModel, owner_user_id)
            if row is None:
                timestamp = utc_now()
                row = UserChatConfigurationModel(
                    owner_user_id=owner_user_id,
                    system_prompt_id=system_prompt_id,
                    skill_ids=list(skill_ids),
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(row)
                await session.commit()
        return _user_chat_configuration_record(row)

    async def update(
        self, *, owner_user_id: str, system_prompt_id: str, skill_ids: list[str]
    ) -> UserChatConfigurationRecord:
        async with self._session_factory() as session:
            row = await session.get(UserChatConfigurationModel, owner_user_id)
            timestamp = utc_now()
            if row is None:
                row = UserChatConfigurationModel(
                    owner_user_id=owner_user_id,
                    system_prompt_id=system_prompt_id,
                    skill_ids=list(skill_ids),
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(row)
            else:
                row.system_prompt_id = system_prompt_id
                row.skill_ids = list(skill_ids)
                row.updated_at = timestamp
            await session.commit()
        return _user_chat_configuration_record(row)


class SQLiteUserChatPromptRepository:
    """SQLite owner-scoped editable prompt persistence."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def ensure_default(
        self,
        *,
        owner_user_id: str,
        label: str,
        content: str,
    ) -> UserChatPromptRecord:
        async with self._session_factory() as session:
            row = (
                await session.scalars(
                    select(UserChatPromptModel).where(
                        UserChatPromptModel.owner_user_id == owner_user_id,
                        UserChatPromptModel.is_default.is_(True),
                    )
                )
            ).first()
            if row is None:
                timestamp = utc_now()
                row = UserChatPromptModel(
                    id=f"prompt_{_uuid_hex()}",
                    owner_user_id=owner_user_id,
                    label=label,
                    content=content,
                    is_default=True,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                session.add(row)
                await session.commit()
        return _user_chat_prompt_record(row)

    async def create(
        self,
        *,
        owner_user_id: str,
        prompt_id: str,
        label: str,
        content: str,
        is_default: bool = False,
    ) -> UserChatPromptRecord:
        timestamp = utc_now()
        row = UserChatPromptModel(
            id=prompt_id,
            owner_user_id=owner_user_id,
            label=label,
            content=content,
            is_default=is_default,
            created_at=timestamp,
            updated_at=timestamp,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
        return _user_chat_prompt_record(row)

    async def get(
        self,
        *,
        owner_user_id: str,
        prompt_id: str,
    ) -> UserChatPromptRecord | None:
        stmt = select(UserChatPromptModel).where(
            UserChatPromptModel.id == prompt_id,
            UserChatPromptModel.owner_user_id == owner_user_id,
        )
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).one_or_none()
        return _user_chat_prompt_record(row) if row is not None else None

    async def list(self, *, owner_user_id: str) -> list[UserChatPromptRecord]:
        stmt = (
            select(UserChatPromptModel)
            .where(UserChatPromptModel.owner_user_id == owner_user_id)
            .order_by(
                UserChatPromptModel.is_default.desc(),
                UserChatPromptModel.updated_at.desc(),
                UserChatPromptModel.id.asc(),
            )
        )
        async with self._session_factory() as session:
            rows = list((await session.scalars(stmt)).all())
        return [_user_chat_prompt_record(row) for row in rows]

    async def update(
        self,
        *,
        owner_user_id: str,
        prompt_id: str,
        label: str,
        content: str,
    ) -> UserChatPromptRecord | None:
        async with self._session_factory() as session:
            row = (
                await session.scalars(
                    select(UserChatPromptModel).where(
                        UserChatPromptModel.id == prompt_id,
                        UserChatPromptModel.owner_user_id == owner_user_id,
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            row.label = label
            row.content = content
            row.updated_at = utc_now()
            await session.commit()
        return _user_chat_prompt_record(row)

    async def delete(self, *, owner_user_id: str, prompt_id: str) -> bool:
        async with self._session_factory() as session:
            row = (
                await session.scalars(
                    select(UserChatPromptModel).where(
                        UserChatPromptModel.id == prompt_id,
                        UserChatPromptModel.owner_user_id == owner_user_id,
                    )
                )
            ).one_or_none()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
        return True


class SQLiteUserChatSkillRepository:
    """SQLite owner-scoped uploaded Skill persistence."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        *,
        owner_user_id: str,
        skill_id: str,
        filename: str,
        name: str,
        description: str,
        content: str,
        size_bytes: int,
    ) -> UserChatSkillRecord:
        timestamp = utc_now()
        row = UserChatSkillModel(
            id=skill_id,
            owner_user_id=owner_user_id,
            filename=filename,
            name=name,
            description=description,
            content=content,
            size_bytes=size_bytes,
            created_at=timestamp,
            updated_at=timestamp,
        )
        async with self._session_factory() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise ValueError(f"Skill name '{name}' 已存在，请使用不同的 name。") from exc
        return _user_chat_skill_record(row)

    async def get(
        self,
        *,
        owner_user_id: str,
        skill_id: str,
    ) -> UserChatSkillRecord | None:
        stmt = select(UserChatSkillModel).where(
            UserChatSkillModel.id == skill_id,
            UserChatSkillModel.owner_user_id == owner_user_id,
        )
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).one_or_none()
        return _user_chat_skill_record(row) if row is not None else None

    async def list(self, *, owner_user_id: str) -> list[UserChatSkillRecord]:
        stmt = (
            select(UserChatSkillModel)
            .where(UserChatSkillModel.owner_user_id == owner_user_id)
            .order_by(UserChatSkillModel.updated_at.desc(), UserChatSkillModel.id.asc())
        )
        async with self._session_factory() as session:
            rows = list((await session.scalars(stmt)).all())
        return [_user_chat_skill_record(row) for row in rows]

    async def delete(self, *, owner_user_id: str, skill_id: str) -> bool:
        async with self._session_factory() as session:
            row = (
                await session.scalars(
                    select(UserChatSkillModel).where(
                        UserChatSkillModel.id == skill_id,
                        UserChatSkillModel.owner_user_id == owner_user_id,
                    )
                )
            ).one_or_none()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
        return True


class SQLiteToolCallAuditRepository:
    """SQLite implementation of generic Agent tool call audit persistence."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_for_chat_session(
        self,
        *,
        owner_user_id: str,
        audit_id: str,
        chat_session_id: str,
        tool_name: str,
        arguments: JsonDict | None = None,
        started_at: datetime | None = None,
    ) -> AgentToolCallAuditRecord:
        timestamp = started_at or utc_now()
        row = AgentToolCallAuditModel(
            id=audit_id,
            owner_user_id=owner_user_id,
            chat_session_id=chat_session_id,
            diagnostic_task_id=None,
            tool_name=tool_name,
            status="started",
            arguments=arguments or {},
            result_summary=None,
            error_message=None,
            started_at=timestamp,
            completed_at=None,
            duration_ms=None,
            created_at=timestamp,
        )
        async with self._session_factory() as session:
            await _require_chat_session(session, owner_user_id, chat_session_id)
            session.add(row)
            await session.commit()
        return _agent_tool_call_audit_record(row)

    async def create_for_diagnostic_task(
        self,
        *,
        owner_user_id: str,
        audit_id: str,
        diagnostic_task_id: str,
        tool_name: str,
        arguments: JsonDict | None = None,
        started_at: datetime | None = None,
    ) -> AgentToolCallAuditRecord:
        timestamp = started_at or utc_now()
        row = AgentToolCallAuditModel(
            id=audit_id,
            owner_user_id=owner_user_id,
            chat_session_id=None,
            diagnostic_task_id=diagnostic_task_id,
            tool_name=tool_name,
            status="started",
            arguments=arguments or {},
            result_summary=None,
            error_message=None,
            started_at=timestamp,
            completed_at=None,
            duration_ms=None,
            created_at=timestamp,
        )
        async with self._session_factory() as session:
            await _require_task(session, owner_user_id, diagnostic_task_id)
            session.add(row)
            await session.commit()
        return _agent_tool_call_audit_record(row)

    async def finalize(
        self,
        *,
        owner_user_id: str,
        audit_id: str,
        status: str,
        result_summary: str | None = None,
        error_message: str | None = None,
        completed_at: datetime | None = None,
    ) -> AgentToolCallAuditRecord | None:
        timestamp = completed_at or utc_now()
        async with self._session_factory() as session:
            row = (
                await session.scalars(
                    select(AgentToolCallAuditModel).where(
                        AgentToolCallAuditModel.id == audit_id,
                        AgentToolCallAuditModel.owner_user_id == owner_user_id,
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            row.status = status
            row.result_summary = result_summary
            row.error_message = error_message
            row.completed_at = timestamp
            row.duration_ms = max(
                0,
                round((timestamp - _ensure_utc(row.started_at)).total_seconds() * 1000),
            )
            await session.commit()
        return _agent_tool_call_audit_record(row)

    async def list_for_chat_session(
        self,
        *,
        owner_user_id: str,
        chat_session_id: str,
    ) -> list[AgentToolCallAuditRecord]:
        async with self._session_factory() as session:
            await _require_chat_session(session, owner_user_id, chat_session_id)
            rows = list(
                (
                    await session.scalars(
                        select(AgentToolCallAuditModel)
                        .where(
                            AgentToolCallAuditModel.owner_user_id == owner_user_id,
                            AgentToolCallAuditModel.chat_session_id == chat_session_id,
                        )
                        .order_by(
                            AgentToolCallAuditModel.created_at.asc(),
                            AgentToolCallAuditModel.id.asc(),
                        )
                    )
                ).all()
            )
        return [_agent_tool_call_audit_record(row) for row in rows]

    async def list_for_diagnostic_task(
        self,
        *,
        owner_user_id: str,
        diagnostic_task_id: str,
    ) -> list[AgentToolCallAuditRecord]:
        async with self._session_factory() as session:
            await _require_task(session, owner_user_id, diagnostic_task_id)
            rows = list(
                (
                    await session.scalars(
                        select(AgentToolCallAuditModel)
                        .where(
                            AgentToolCallAuditModel.owner_user_id == owner_user_id,
                            AgentToolCallAuditModel.diagnostic_task_id == diagnostic_task_id,
                        )
                        .order_by(
                            AgentToolCallAuditModel.created_at.asc(),
                            AgentToolCallAuditModel.id.asc(),
                        )
                    )
                ).all()
            )
        return [_agent_tool_call_audit_record(row) for row in rows]


class SQLiteKnowledgeDocumentRepository:
    """SQLite implementation of knowledge document metadata persistence."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def lexical_revision(
        self, *, owner_user_id: str, knowledge_base_ids: Sequence[str]
    ) -> str:
        stmt = select(
            KnowledgeDocumentModel.id, KnowledgeDocumentModel.content_hash,
            KnowledgeDocumentModel.index_status, KnowledgeDocumentModel.updated_at,
        ).where(
            KnowledgeDocumentModel.owner_user_id == owner_user_id,
            KnowledgeDocumentModel.knowledge_base_id.in_(knowledge_base_ids),
            KnowledgeDocumentModel.deleted_at.is_(None),
        ).order_by(KnowledgeDocumentModel.id)
        async with self._session_factory() as session:
            rows = (await session.execute(stmt)).all()
        digest = sha256()
        for document_id, content_hash, index_status, updated_at in rows:
            digest.update(
                f"{document_id}\0{content_hash}\0{index_status}\0{updated_at.isoformat()}\n".encode()
            )
        return digest.hexdigest()

    async def create_document(
        self,
        *,
        owner_user_id: str,
        document_id: str,
        knowledge_base_id: str,
        filename: str,
        size_bytes: int,
        mime_type: str,
        content_hash: str,
        status: str = "ready",
        index_status: str = "pending",
        metadata: JsonDict | None = None,
        source: str | None = None,
        uploaded_at: datetime | None = None,
    ) -> KnowledgeDocumentRecord:
        timestamp = uploaded_at or utc_now()
        row = KnowledgeDocumentModel(
            id=document_id,
            owner_user_id=owner_user_id,
            knowledge_base_id=knowledge_base_id,
            filename=filename,
            size_bytes=size_bytes,
            mime_type=mime_type,
            content_hash=content_hash,
            status=status,
            index_status=index_status,
            source=source,
            metadata_json=metadata or {},
            uploaded_at=timestamp,
            updated_at=timestamp,
            deleted_at=None,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
        return _knowledge_document_record(row)

    async def get_document(
        self,
        *,
        owner_user_id: str,
        knowledge_base_id: str,
        document_id: str,
        include_deleted: bool = False,
    ) -> KnowledgeDocumentRecord | None:
        stmt = select(KnowledgeDocumentModel).where(
            KnowledgeDocumentModel.id == document_id,
            KnowledgeDocumentModel.owner_user_id == owner_user_id,
            KnowledgeDocumentModel.knowledge_base_id == knowledge_base_id,
        )
        stmt = _apply_deleted_filter(stmt, include_deleted)
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).one_or_none()
        return _knowledge_document_record(row) if row is not None else None

    async def list_documents(
        self,
        *,
        owner_user_id: str,
        knowledge_base_id: str,
        time_range: TimeRangeFilter | None = None,
        include_deleted: bool = False,
    ) -> list[KnowledgeDocumentRecord]:
        stmt = select(KnowledgeDocumentModel).where(
            KnowledgeDocumentModel.owner_user_id == owner_user_id,
            KnowledgeDocumentModel.knowledge_base_id == knowledge_base_id,
        )
        stmt = _apply_deleted_filter(stmt, include_deleted)
        stmt = _apply_time_range(stmt, KnowledgeDocumentModel.uploaded_at, time_range)
        stmt = stmt.order_by(
            KnowledgeDocumentModel.uploaded_at.desc(),
            KnowledgeDocumentModel.id.asc(),
        )
        async with self._session_factory() as session:
            rows = list((await session.scalars(stmt)).all())
        return [_knowledge_document_record(row) for row in rows]

    async def find_active_by_hash(
        self,
        *,
        owner_user_id: str,
        knowledge_base_id: str,
        content_hash: str,
    ) -> KnowledgeDocumentRecord | None:
        stmt = (
            select(KnowledgeDocumentModel)
            .where(
                KnowledgeDocumentModel.owner_user_id == owner_user_id,
                KnowledgeDocumentModel.knowledge_base_id == knowledge_base_id,
                KnowledgeDocumentModel.content_hash == content_hash,
                KnowledgeDocumentModel.deleted_at.is_(None),
                KnowledgeDocumentModel.status != "deleted",
            )
            .order_by(KnowledgeDocumentModel.uploaded_at.desc(), KnowledgeDocumentModel.id.asc())
        )
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).first()
        return _knowledge_document_record(row) if row is not None else None

    async def mark_document_deleted(
        self,
        *,
        owner_user_id: str,
        knowledge_base_id: str,
        document_id: str,
        deleted_at: datetime | None = None,
    ) -> KnowledgeDocumentRecord | None:
        timestamp = deleted_at or utc_now()
        stmt = select(KnowledgeDocumentModel).where(
            KnowledgeDocumentModel.id == document_id,
            KnowledgeDocumentModel.owner_user_id == owner_user_id,
            KnowledgeDocumentModel.knowledge_base_id == knowledge_base_id,
        )
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).one_or_none()
            if row is None:
                return None
            row.status = "deleted"
            row.updated_at = timestamp
            row.deleted_at = timestamp
            await session.commit()
        return _knowledge_document_record(row)

    async def update_index_status(
        self,
        *,
        owner_user_id: str,
        knowledge_base_id: str,
        document_id: str,
        index_status: str,
        updated_at: datetime | None = None,
    ) -> KnowledgeDocumentRecord | None:
        timestamp = updated_at or utc_now()
        stmt = select(KnowledgeDocumentModel).where(
            KnowledgeDocumentModel.id == document_id,
            KnowledgeDocumentModel.owner_user_id == owner_user_id,
            KnowledgeDocumentModel.knowledge_base_id == knowledge_base_id,
        )
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).one_or_none()
            if row is None:
                return None
            row.index_status = index_status
            row.updated_at = timestamp
            await session.commit()
        return _knowledge_document_record(row)


class SQLiteDocumentIndexTaskRepository:
    """SQLite implementation of document index task persistence."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_task(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        knowledge_base_id: str,
        document_id: str,
        status: str = "pending",
        retry_of_task_id: str | None = None,
        created_at: datetime | None = None,
    ) -> DocumentIndexTaskRecord:
        timestamp = created_at or utc_now()
        row = DocumentIndexTaskModel(
            id=task_id,
            owner_user_id=owner_user_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
            status=status,
            failure_reason=None,
            retry_of_task_id=retry_of_task_id,
            created_at=timestamp,
            updated_at=timestamp,
            started_at=None,
            completed_at=None,
        )
        async with self._session_factory() as session:
            await _require_document(session, owner_user_id, knowledge_base_id, document_id)
            session.add(row)
            await session.commit()
        return _document_index_task_record(row)

    async def create_retry(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        retry_of_task_id: str,
        created_at: datetime | None = None,
    ) -> DocumentIndexTaskRecord:
        async with self._session_factory() as session:
            prior = await _require_document_index_task(session, owner_user_id, retry_of_task_id)
            timestamp = created_at or utc_now()
            row = DocumentIndexTaskModel(
                id=task_id,
                owner_user_id=owner_user_id,
                knowledge_base_id=prior.knowledge_base_id,
                document_id=prior.document_id,
                status="pending",
                failure_reason=None,
                retry_of_task_id=prior.id,
                created_at=timestamp,
                updated_at=timestamp,
                started_at=None,
                completed_at=None,
            )
            session.add(row)
            await session.commit()
        return _document_index_task_record(row)

    async def get_task(
        self,
        *,
        owner_user_id: str,
        task_id: str,
    ) -> DocumentIndexTaskRecord | None:
        stmt = select(DocumentIndexTaskModel).where(
            DocumentIndexTaskModel.id == task_id,
            DocumentIndexTaskModel.owner_user_id == owner_user_id,
        )
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).one_or_none()
        return _document_index_task_record(row) if row is not None else None

    async def list_tasks_for_document(
        self,
        *,
        owner_user_id: str,
        knowledge_base_id: str,
        document_id: str,
    ) -> list[DocumentIndexTaskRecord]:
        stmt = (
            select(DocumentIndexTaskModel)
            .where(
                DocumentIndexTaskModel.owner_user_id == owner_user_id,
                DocumentIndexTaskModel.knowledge_base_id == knowledge_base_id,
                DocumentIndexTaskModel.document_id == document_id,
            )
            .order_by(DocumentIndexTaskModel.created_at.asc(), DocumentIndexTaskModel.id.asc())
        )
        async with self._session_factory() as session:
            rows = list((await session.scalars(stmt)).all())
        return [_document_index_task_record(row) for row in rows]

    async def mark_running(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        started_at: datetime | None = None,
    ) -> DocumentIndexTaskRecord | None:
        timestamp = started_at or utc_now()
        return await self._update_task(
            owner_user_id=owner_user_id,
            task_id=task_id,
            status="running",
            updated_at=timestamp,
            started_at=timestamp,
            completed_at=None,
            failure_reason=None,
        )

    async def mark_succeeded(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        completed_at: datetime | None = None,
    ) -> DocumentIndexTaskRecord | None:
        timestamp = completed_at or utc_now()
        return await self._update_task(
            owner_user_id=owner_user_id,
            task_id=task_id,
            status="succeeded",
            updated_at=timestamp,
            completed_at=timestamp,
            failure_reason=None,
        )

    async def mark_failed(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        failure_reason: str,
        completed_at: datetime | None = None,
    ) -> DocumentIndexTaskRecord | None:
        timestamp = completed_at or utc_now()
        return await self._update_task(
            owner_user_id=owner_user_id,
            task_id=task_id,
            status="failed",
            updated_at=timestamp,
            completed_at=timestamp,
            failure_reason=failure_reason,
        )

    async def _update_task(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        status: str,
        updated_at: datetime,
        started_at: datetime | None | object = _UNSET,
        completed_at: datetime | None | object = _UNSET,
        failure_reason: str | None | object = _UNSET,
    ) -> DocumentIndexTaskRecord | None:
        stmt = select(DocumentIndexTaskModel).where(
            DocumentIndexTaskModel.id == task_id,
            DocumentIndexTaskModel.owner_user_id == owner_user_id,
        )
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).one_or_none()
            if row is None:
                return None
            row.status = status
            row.updated_at = updated_at
            if started_at is not _UNSET:
                row.started_at = cast(datetime | None, started_at)
            if completed_at is not _UNSET:
                row.completed_at = cast(datetime | None, completed_at)
            if failure_reason is not _UNSET:
                row.failure_reason = cast(str | None, failure_reason)
            await session.commit()
        return _document_index_task_record(row)

    async def mark_cancelled(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        completed_at: datetime | None = None,
    ) -> DocumentIndexTaskRecord | None:
        timestamp = completed_at or utc_now()
        return await self._update_task(
            owner_user_id=owner_user_id,
            task_id=task_id,
            status="cancelled",
            updated_at=timestamp,
            completed_at=timestamp,
        )


class SQLiteDiagnosticMemoryRepository:
    """SQLite implementation of AIOps diagnostic memory persistence."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_task(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        status: str,
        query: str,
        input_payload: JsonDict | None = None,
        result_payload: JsonDict | None = None,
        created_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> DiagnosticTaskRecord:
        timestamp = created_at or utc_now()
        row = DiagnosticTaskModel(
            id=task_id,
            owner_user_id=owner_user_id,
            status=status,
            query=query,
            input_payload=input_payload or {},
            result_payload=result_payload or {},
            created_at=timestamp,
            updated_at=timestamp,
            completed_at=completed_at,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
        return _diagnostic_task_record(row)

    async def get_task(
        self,
        *,
        owner_user_id: str,
        task_id: str,
    ) -> DiagnosticTaskRecord | None:
        stmt = select(DiagnosticTaskModel).where(
            DiagnosticTaskModel.id == task_id,
            DiagnosticTaskModel.owner_user_id == owner_user_id,
        )
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).one_or_none()
        return _diagnostic_task_record(row) if row is not None else None

    async def update_task(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        status: str,
        result_payload: JsonDict | None = None,
        completed_at: datetime | None = None,
    ) -> DiagnosticTaskRecord | None:
        async with self._session_factory() as session:
            row = await _find_diagnostic_task(session, owner_user_id, task_id)
            if row is None:
                return None
            row.status = status
            row.updated_at = utc_now()
            if result_payload is not None:
                row.result_payload = result_payload
            if completed_at is not None:
                row.completed_at = completed_at
            await session.commit()
        return _diagnostic_task_record(row)

    async def list_tasks(
        self,
        *,
        owner_user_id: str,
        time_range: TimeRangeFilter | None = None,
    ) -> list[DiagnosticTaskRecord]:
        stmt = _apply_time_range(
            select(DiagnosticTaskModel).where(DiagnosticTaskModel.owner_user_id == owner_user_id),
            DiagnosticTaskModel.created_at,
            time_range,
        )
        stmt = stmt.order_by(DiagnosticTaskModel.created_at.asc(), DiagnosticTaskModel.id.asc())
        async with self._session_factory() as session:
            rows = list((await session.scalars(stmt)).all())
        return [_diagnostic_task_record(row) for row in rows]

    async def add_report(
        self,
        *,
        owner_user_id: str,
        report_id: str,
        task_id: str,
        title: str,
        content: str,
        payload: JsonDict | None = None,
        created_at: datetime | None = None,
    ) -> DiagnosticReportRecord:
        row = DiagnosticReportModel(
            id=report_id,
            owner_user_id=owner_user_id,
            task_id=task_id,
            title=title,
            content=content,
            payload=payload or {},
            created_at=created_at or utc_now(),
        )
        async with self._session_factory() as session:
            await _require_task(session, owner_user_id, task_id)
            session.add(row)
            await session.commit()
        return _diagnostic_report_record(row)

    async def list_reports(
        self,
        *,
        owner_user_id: str,
        task_id: str,
    ) -> list[DiagnosticReportRecord]:
        stmt = (
            select(DiagnosticReportModel)
            .where(
                DiagnosticReportModel.owner_user_id == owner_user_id,
                DiagnosticReportModel.task_id == task_id,
            )
            .order_by(DiagnosticReportModel.created_at.asc(), DiagnosticReportModel.id.asc())
        )
        async with self._session_factory() as session:
            rows = list((await session.scalars(stmt)).all())
        return [_diagnostic_report_record(row) for row in rows]

    async def get_report(
        self,
        *,
        owner_user_id: str,
        report_id: str,
    ) -> DiagnosticReportRecord | None:
        stmt = select(DiagnosticReportModel).where(
            DiagnosticReportModel.id == report_id,
            DiagnosticReportModel.owner_user_id == owner_user_id,
        )
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).one_or_none()
        return _diagnostic_report_record(row) if row is not None else None

    async def create_case(
        self,
        *,
        owner_user_id: str,
        case_id: str,
        task_id: str,
        report_id: str,
        document_id: str,
        index_task_id: str,
        alert_name: str,
        service: str,
        keywords: list[str],
        root_cause: str,
        remediation: str,
        summary: str,
        evidence_ids: list[str],
    ) -> DiagnosticCaseRecord:
        row = DiagnosticCaseModel(
            id=case_id,
            owner_user_id=owner_user_id,
            task_id=task_id,
            report_id=report_id,
            document_id=document_id,
            index_task_id=index_task_id,
            alert_name=alert_name,
            service=service,
            keywords=keywords,
            root_cause=root_cause,
            remediation=remediation,
            summary=summary,
            evidence_ids=evidence_ids,
        )
        async with self._session_factory() as session:
            existing = await _find_diagnostic_case_for_task(session, owner_user_id, task_id)
            if existing is not None:
                return _diagnostic_case_record(existing)
            await _require_diagnostic_report(session, owner_user_id, task_id, report_id)
            index_task = await _require_document_index_task(session, owner_user_id, index_task_id)
            if index_task.document_id != document_id:
                raise TenantScopeError(
                    f"Document index task does not match document: {index_task_id}"
                )
            await _require_document(
                session,
                owner_user_id,
                index_task.knowledge_base_id,
                document_id,
            )
            session.add(row)
            await session.commit()
        return _diagnostic_case_record(row)

    async def get_case_for_task(
        self,
        *,
        owner_user_id: str,
        task_id: str,
    ) -> DiagnosticCaseRecord | None:
        async with self._session_factory() as session:
            row = await _find_diagnostic_case_for_task(session, owner_user_id, task_id)
        return _diagnostic_case_record(row) if row is not None else None

    async def get_case(
        self,
        *,
        owner_user_id: str,
        case_id: str,
    ) -> DiagnosticCaseRecord | None:
        async with self._session_factory() as session:
            row = await _find_diagnostic_case(session, owner_user_id, case_id)
        return _diagnostic_case_record(row) if row is not None else None

    async def list_cases(self, *, owner_user_id: str) -> list[DiagnosticCaseRecord]:
        stmt = (
            select(DiagnosticCaseModel)
            .where(DiagnosticCaseModel.owner_user_id == owner_user_id)
            .order_by(DiagnosticCaseModel.created_at.desc(), DiagnosticCaseModel.id.asc())
        )
        async with self._session_factory() as session:
            rows = list((await session.scalars(stmt)).all())
        return [_diagnostic_case_record(row) for row in rows]

    async def create_step(
        self,
        *,
        owner_user_id: str,
        step_id: str,
        task_id: str,
        sequence: int,
        phase: str,
        status: str,
        payload: JsonDict | None = None,
        created_at: datetime | None = None,
    ) -> DiagnosticStepRecord:
        row = DiagnosticStepModel(
            id=step_id,
            owner_user_id=owner_user_id,
            task_id=task_id,
            sequence=sequence,
            phase=phase,
            status=status,
            payload=payload or {},
            created_at=created_at or utc_now(),
        )
        async with self._session_factory() as session:
            await _require_task(session, owner_user_id, task_id)
            session.add(row)
            await session.commit()
        return _diagnostic_step_record(row)

    async def list_steps(
        self,
        *,
        owner_user_id: str,
        task_id: str,
    ) -> list[DiagnosticStepRecord]:
        stmt = (
            select(DiagnosticStepModel)
            .where(
                DiagnosticStepModel.owner_user_id == owner_user_id,
                DiagnosticStepModel.task_id == task_id,
            )
            .order_by(DiagnosticStepModel.sequence.asc(), DiagnosticStepModel.id.asc())
        )
        async with self._session_factory() as session:
            await _require_task(session, owner_user_id, task_id)
            rows = list((await session.scalars(stmt)).all())
        return [_diagnostic_step_record(row) for row in rows]

    async def get_step(
        self,
        *,
        owner_user_id: str,
        step_id: str,
    ) -> DiagnosticStepRecord | None:
        stmt = select(DiagnosticStepModel).where(
            DiagnosticStepModel.id == step_id,
            DiagnosticStepModel.owner_user_id == owner_user_id,
        )
        async with self._session_factory() as session:
            row = (await session.scalars(stmt)).one_or_none()
        return _diagnostic_step_record(row) if row is not None else None

    async def create_evidence(
        self,
        *,
        owner_user_id: str,
        evidence_id: str,
        task_id: str,
        kind: str,
        source: str,
        summary: str,
        payload: JsonDict | None = None,
        step_id: str | None = None,
        tool_call_id: str | None = None,
        created_at: datetime | None = None,
    ) -> DiagnosticEvidenceRecord:
        row = DiagnosticEvidenceModel(
            id=evidence_id,
            owner_user_id=owner_user_id,
            task_id=task_id,
            step_id=step_id,
            tool_call_id=tool_call_id,
            kind=kind,
            source=source,
            summary=summary,
            payload=payload or {},
            created_at=created_at or utc_now(),
        )
        async with self._session_factory() as session:
            await _require_task(session, owner_user_id, task_id)
            if step_id is not None:
                await _require_diagnostic_step(session, owner_user_id, task_id, step_id)
            session.add(row)
            await session.commit()
        return _diagnostic_evidence_record(row)

    async def list_evidence(
        self,
        *,
        owner_user_id: str,
        task_id: str,
    ) -> list[DiagnosticEvidenceRecord]:
        stmt = (
            select(DiagnosticEvidenceModel)
            .where(
                DiagnosticEvidenceModel.owner_user_id == owner_user_id,
                DiagnosticEvidenceModel.task_id == task_id,
            )
            .order_by(DiagnosticEvidenceModel.created_at.asc(), DiagnosticEvidenceModel.id.asc())
        )
        async with self._session_factory() as session:
            await _require_task(session, owner_user_id, task_id)
            rows = list((await session.scalars(stmt)).all())
        return [_diagnostic_evidence_record(row) for row in rows]

    async def link_report_evidence(
        self,
        *,
        owner_user_id: str,
        link_id: str,
        task_id: str,
        report_id: str,
        evidence_id: str,
        created_at: datetime | None = None,
    ) -> ReportEvidenceLinkRecord:
        row = ReportEvidenceLinkModel(
            id=link_id,
            owner_user_id=owner_user_id,
            task_id=task_id,
            report_id=report_id,
            evidence_id=evidence_id,
            created_at=created_at or utc_now(),
        )
        async with self._session_factory() as session:
            await _require_task(session, owner_user_id, task_id)
            await _require_diagnostic_report(session, owner_user_id, task_id, report_id)
            await _require_diagnostic_evidence(session, owner_user_id, task_id, evidence_id)
            session.add(row)
            await session.commit()
        return _report_evidence_link_record(row)

    async def list_report_evidence_links(
        self,
        *,
        owner_user_id: str,
        task_id: str,
    ) -> list[ReportEvidenceLinkRecord]:
        stmt = (
            select(ReportEvidenceLinkModel)
            .where(
                ReportEvidenceLinkModel.owner_user_id == owner_user_id,
                ReportEvidenceLinkModel.task_id == task_id,
            )
            .order_by(ReportEvidenceLinkModel.created_at.asc(), ReportEvidenceLinkModel.id.asc())
        )
        async with self._session_factory() as session:
            await _require_task(session, owner_user_id, task_id)
            rows = list((await session.scalars(stmt)).all())
        return [_report_evidence_link_record(row) for row in rows]

    async def add_tool_call_audit(
        self,
        *,
        owner_user_id: str,
        audit_id: str,
        task_id: str,
        tool_name: str,
        status: str,
        arguments: JsonDict | None = None,
        result_payload: JsonDict | None = None,
        error_message: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> ToolCallAuditRecord:
        created_at = started_at or utc_now()
        row = ToolCallAuditModel(
            id=audit_id,
            owner_user_id=owner_user_id,
            task_id=task_id,
            tool_name=tool_name,
            status=status,
            arguments=arguments or {},
            result_payload=result_payload or {},
            error_message=error_message,
            started_at=created_at,
            completed_at=completed_at,
            created_at=created_at,
        )
        async with self._session_factory() as session:
            await _require_task(session, owner_user_id, task_id)
            session.add(row)
            await session.commit()
        return _tool_call_audit_record(row)

    async def list_tool_call_audits(
        self,
        *,
        owner_user_id: str,
        task_id: str,
    ) -> list[ToolCallAuditRecord]:
        stmt = (
            select(ToolCallAuditModel)
            .where(
                ToolCallAuditModel.owner_user_id == owner_user_id,
                ToolCallAuditModel.task_id == task_id,
            )
            .order_by(ToolCallAuditModel.created_at.asc(), ToolCallAuditModel.id.asc())
        )
        async with self._session_factory() as session:
            rows = list((await session.scalars(stmt)).all())
        return [_tool_call_audit_record(row) for row in rows]

    async def save_checkpoint(
        self,
        *,
        owner_user_id: str,
        checkpoint_record_id: str,
        task_id: str,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
        checkpoint_payload: JsonDict | None = None,
        metadata: JsonDict | None = None,
        created_at: datetime | None = None,
    ) -> GraphCheckpointRecord:
        row = GraphCheckpointModel(
            id=checkpoint_record_id,
            owner_user_id=owner_user_id,
            task_id=task_id,
            thread_id=thread_id,
            checkpoint_ns=checkpoint_ns,
            checkpoint_id=checkpoint_id,
            checkpoint_payload=checkpoint_payload or {},
            metadata_json=metadata or {},
            created_at=created_at or utc_now(),
        )
        async with self._session_factory() as session:
            await _require_task(session, owner_user_id, task_id)
            session.add(row)
            await session.commit()
        return _graph_checkpoint_record(row)

    async def list_checkpoints(
        self,
        *,
        owner_user_id: str,
        task_id: str,
    ) -> list[GraphCheckpointRecord]:
        stmt = (
            select(GraphCheckpointModel)
            .where(
                GraphCheckpointModel.owner_user_id == owner_user_id,
                GraphCheckpointModel.task_id == task_id,
            )
            .order_by(GraphCheckpointModel.created_at.asc(), GraphCheckpointModel.id.asc())
        )
        async with self._session_factory() as session:
            rows = list((await session.scalars(stmt)).all())
        return [_graph_checkpoint_record(row) for row in rows]


def create_sqlite_memory_repositories(
    session_factory: async_sessionmaker[AsyncSession],
) -> MemoryRepositories:
    """Create a repository bundle backed by SQLite-compatible SQLAlchemy sessions."""
    from super_ai.memory.extended_sqlite import (
        SQLiteBackgroundJobRepository,
        SQLiteMcpConnectionRepository,
        SQLiteRemediationApprovalRepository,
        SQLiteUserFeedbackRepository,
    )

    return MemoryRepositories(
        chat=SQLiteChatMemoryRepository(session_factory),
        chat_configurations=SQLiteUserChatConfigurationRepository(session_factory),
        chat_prompts=SQLiteUserChatPromptRepository(session_factory),
        chat_skills=SQLiteUserChatSkillRepository(session_factory),
        documents=SQLiteKnowledgeDocumentRepository(session_factory),
        document_index_tasks=SQLiteDocumentIndexTaskRepository(session_factory),
        diagnostics=SQLiteDiagnosticMemoryRepository(session_factory),
        tool_call_audits=SQLiteToolCallAuditRepository(session_factory),
        background_jobs=SQLiteBackgroundJobRepository(session_factory),
        feedback=SQLiteUserFeedbackRepository(session_factory),
        mcp_connections=SQLiteMcpConnectionRepository(session_factory),
        remediation_approvals=SQLiteRemediationApprovalRepository(session_factory),
    )


def _user_chat_configuration_record(row: UserChatConfigurationModel) -> UserChatConfigurationRecord:
    return UserChatConfigurationRecord(
        owner_user_id=row.owner_user_id,
        system_prompt_id=row.system_prompt_id,
        skill_ids=list(row.skill_ids),
        created_at=_ensure_utc(row.created_at),
        updated_at=_ensure_utc(row.updated_at),
    )


def _user_chat_prompt_record(row: UserChatPromptModel) -> UserChatPromptRecord:
    return UserChatPromptRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        label=row.label,
        content=row.content,
        is_default=row.is_default,
        created_at=_ensure_utc(row.created_at),
        updated_at=_ensure_utc(row.updated_at),
    )


def _user_chat_skill_record(row: UserChatSkillModel) -> UserChatSkillRecord:
    return UserChatSkillRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        filename=row.filename,
        name=row.name,
        description=row.description,
        content=row.content,
        size_bytes=row.size_bytes,
        created_at=_ensure_utc(row.created_at),
        updated_at=_ensure_utc(row.updated_at),
    )


def _uuid_hex() -> str:
    return uuid4().hex


async def _require_chat_session(
    session: AsyncSession,
    owner_user_id: str,
    session_id: str,
) -> ChatSessionModel:
    row = await _find_chat_session(session, owner_user_id, session_id)
    if row is None:
        raise TenantScopeError(f"Chat session is not accessible: {session_id}")
    return row


async def _find_chat_session(
    session: AsyncSession,
    owner_user_id: str,
    session_id: str,
) -> ChatSessionModel | None:
    stmt = select(ChatSessionModel).where(
        ChatSessionModel.id == session_id,
        ChatSessionModel.owner_user_id == owner_user_id,
    )
    return (await session.scalars(stmt)).one_or_none()


async def _require_task(session: AsyncSession, owner_user_id: str, task_id: str) -> None:
    if await _find_diagnostic_task(session, owner_user_id, task_id) is None:
        raise TenantScopeError(f"Diagnostic task is not accessible: {task_id}")


async def _find_diagnostic_task(
    session: AsyncSession,
    owner_user_id: str,
    task_id: str,
) -> DiagnosticTaskModel | None:
    stmt = select(DiagnosticTaskModel).where(
        DiagnosticTaskModel.id == task_id,
        DiagnosticTaskModel.owner_user_id == owner_user_id,
    )
    return (await session.scalars(stmt)).one_or_none()


async def _find_diagnostic_case_for_task(
    session: AsyncSession,
    owner_user_id: str,
    task_id: str,
) -> DiagnosticCaseModel | None:
    stmt = select(DiagnosticCaseModel).where(
        DiagnosticCaseModel.owner_user_id == owner_user_id,
        DiagnosticCaseModel.task_id == task_id,
    )
    return (await session.scalars(stmt)).one_or_none()


async def _find_diagnostic_case(
    session: AsyncSession,
    owner_user_id: str,
    case_id: str,
) -> DiagnosticCaseModel | None:
    stmt = select(DiagnosticCaseModel).where(
        DiagnosticCaseModel.id == case_id,
        DiagnosticCaseModel.owner_user_id == owner_user_id,
    )
    return (await session.scalars(stmt)).one_or_none()


async def _require_diagnostic_step(
    session: AsyncSession,
    owner_user_id: str,
    task_id: str,
    step_id: str,
) -> DiagnosticStepModel:
    stmt = select(DiagnosticStepModel).where(
        DiagnosticStepModel.id == step_id,
        DiagnosticStepModel.owner_user_id == owner_user_id,
        DiagnosticStepModel.task_id == task_id,
    )
    row = (await session.scalars(stmt)).one_or_none()
    if row is None:
        raise TenantScopeError(f"Diagnostic step is not accessible: {step_id}")
    return row


async def _require_diagnostic_report(
    session: AsyncSession,
    owner_user_id: str,
    task_id: str,
    report_id: str,
) -> DiagnosticReportModel:
    stmt = select(DiagnosticReportModel).where(
        DiagnosticReportModel.id == report_id,
        DiagnosticReportModel.owner_user_id == owner_user_id,
        DiagnosticReportModel.task_id == task_id,
    )
    row = (await session.scalars(stmt)).one_or_none()
    if row is None:
        raise TenantScopeError(f"Diagnostic report is not accessible: {report_id}")
    return row


async def _require_diagnostic_evidence(
    session: AsyncSession,
    owner_user_id: str,
    task_id: str,
    evidence_id: str,
) -> DiagnosticEvidenceModel:
    stmt = select(DiagnosticEvidenceModel).where(
        DiagnosticEvidenceModel.id == evidence_id,
        DiagnosticEvidenceModel.owner_user_id == owner_user_id,
        DiagnosticEvidenceModel.task_id == task_id,
    )
    row = (await session.scalars(stmt)).one_or_none()
    if row is None:
        raise TenantScopeError(f"Diagnostic evidence is not accessible: {evidence_id}")
    return row


async def _require_document(
    session: AsyncSession,
    owner_user_id: str,
    knowledge_base_id: str,
    document_id: str,
) -> KnowledgeDocumentModel:
    stmt = select(KnowledgeDocumentModel).where(
        KnowledgeDocumentModel.id == document_id,
        KnowledgeDocumentModel.owner_user_id == owner_user_id,
        KnowledgeDocumentModel.knowledge_base_id == knowledge_base_id,
        KnowledgeDocumentModel.deleted_at.is_(None),
        KnowledgeDocumentModel.status != "deleted",
    )
    row = (await session.scalars(stmt)).one_or_none()
    if row is None:
        raise TenantScopeError(f"Document is not accessible: {document_id}")
    return row


async def _require_document_index_task(
    session: AsyncSession,
    owner_user_id: str,
    task_id: str,
) -> DocumentIndexTaskModel:
    stmt = select(DocumentIndexTaskModel).where(
        DocumentIndexTaskModel.id == task_id,
        DocumentIndexTaskModel.owner_user_id == owner_user_id,
    )
    row = (await session.scalars(stmt)).one_or_none()
    if row is None:
        raise TenantScopeError(f"Document index task is not accessible: {task_id}")
    return row


def _apply_time_range(
    stmt: Select[tuple[ModelT]],
    column: Any,
    time_range: TimeRangeFilter | None,
) -> Select[tuple[ModelT]]:
    if time_range is None:
        return stmt
    if time_range.start_at is not None:
        stmt = stmt.where(column >= time_range.start_at)
    if time_range.end_at is not None:
        stmt = stmt.where(column <= time_range.end_at)
    return stmt


def _apply_deleted_filter(
    stmt: Select[tuple[KnowledgeDocumentModel]],
    include_deleted: bool,
) -> Select[tuple[KnowledgeDocumentModel]]:
    if include_deleted:
        return stmt
    return stmt.where(
        KnowledgeDocumentModel.deleted_at.is_(None),
        KnowledgeDocumentModel.status != "deleted",
    )


def _json_dict(value: object) -> JsonDict:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): item for key, item in mapping.items()}
    return {}


def _chat_session_record(row: ChatSessionModel) -> ChatSessionRecord:
    return ChatSessionRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        title=row.title,
        created_at=_ensure_utc(row.created_at),
        updated_at=_ensure_utc(row.updated_at),
        memory_mode=row.memory_mode,
        memory_summary=row.memory_summary,
        compacted_message_count=row.compacted_message_count,
        context_tokens=row.context_tokens,
        last_compacted_at=(
            _ensure_utc(row.last_compacted_at) if row.last_compacted_at is not None else None
        ),
    )


def _chat_message_record(row: ChatMessageModel) -> ChatMessageRecord:
    return ChatMessageRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        session_id=row.session_id,
        role=row.role,
        content=row.content,
        metadata=_json_dict(row.metadata_json),
        created_at=_ensure_utc(row.created_at),
    )


def _knowledge_document_record(row: KnowledgeDocumentModel) -> KnowledgeDocumentRecord:
    return KnowledgeDocumentRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        knowledge_base_id=row.knowledge_base_id,
        filename=row.filename,
        size_bytes=row.size_bytes,
        mime_type=row.mime_type,
        content_hash=row.content_hash,
        status=row.status,
        index_status=row.index_status,
        metadata=_json_dict(row.metadata_json),
        uploaded_at=_ensure_utc(row.uploaded_at),
        updated_at=_ensure_utc(row.updated_at),
        source=row.source,
        deleted_at=_ensure_utc_optional(row.deleted_at),
    )


def _document_index_task_record(row: DocumentIndexTaskModel) -> DocumentIndexTaskRecord:
    return DocumentIndexTaskRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        knowledge_base_id=row.knowledge_base_id,
        document_id=row.document_id,
        status=row.status,
        failure_reason=row.failure_reason,
        retry_of_task_id=row.retry_of_task_id,
        created_at=_ensure_utc(row.created_at),
        updated_at=_ensure_utc(row.updated_at),
        started_at=_ensure_utc_optional(row.started_at),
        completed_at=_ensure_utc_optional(row.completed_at),
    )


def _diagnostic_task_record(row: DiagnosticTaskModel) -> DiagnosticTaskRecord:
    return DiagnosticTaskRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        status=row.status,
        query=row.query,
        input_payload=_json_dict(row.input_payload),
        result_payload=_json_dict(row.result_payload),
        created_at=_ensure_utc(row.created_at),
        updated_at=_ensure_utc(row.updated_at),
        completed_at=_ensure_utc_optional(row.completed_at),
    )


def _diagnostic_report_record(row: DiagnosticReportModel) -> DiagnosticReportRecord:
    return DiagnosticReportRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        task_id=row.task_id,
        title=row.title,
        content=row.content,
        payload=_json_dict(row.payload),
        created_at=_ensure_utc(row.created_at),
    )


def _diagnostic_case_record(row: DiagnosticCaseModel) -> DiagnosticCaseRecord:
    return DiagnosticCaseRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        task_id=row.task_id,
        report_id=row.report_id,
        document_id=row.document_id,
        index_task_id=row.index_task_id,
        alert_name=row.alert_name,
        service=row.service,
        keywords=list(row.keywords),
        root_cause=row.root_cause,
        remediation=row.remediation,
        summary=row.summary,
        evidence_ids=list(row.evidence_ids),
        created_at=_ensure_utc(row.created_at),
    )


def _diagnostic_step_record(row: DiagnosticStepModel) -> DiagnosticStepRecord:
    return DiagnosticStepRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        task_id=row.task_id,
        sequence=row.sequence,
        phase=row.phase,
        status=row.status,
        payload=_json_dict(row.payload),
        created_at=_ensure_utc(row.created_at),
    )


def _diagnostic_evidence_record(row: DiagnosticEvidenceModel) -> DiagnosticEvidenceRecord:
    return DiagnosticEvidenceRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        task_id=row.task_id,
        step_id=row.step_id,
        tool_call_id=row.tool_call_id,
        kind=row.kind,
        source=row.source,
        summary=row.summary,
        payload=_json_dict(row.payload),
        created_at=_ensure_utc(row.created_at),
    )


def _report_evidence_link_record(row: ReportEvidenceLinkModel) -> ReportEvidenceLinkRecord:
    return ReportEvidenceLinkRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        task_id=row.task_id,
        report_id=row.report_id,
        evidence_id=row.evidence_id,
        created_at=_ensure_utc(row.created_at),
    )


def _tool_call_audit_record(row: ToolCallAuditModel) -> ToolCallAuditRecord:
    return ToolCallAuditRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        task_id=row.task_id,
        tool_name=row.tool_name,
        status=row.status,
        arguments=_json_dict(row.arguments),
        result_payload=_json_dict(row.result_payload),
        error_message=row.error_message,
        started_at=_ensure_utc(row.started_at),
        completed_at=_ensure_utc_optional(row.completed_at),
        created_at=_ensure_utc(row.created_at),
    )


def _agent_tool_call_audit_record(row: AgentToolCallAuditModel) -> AgentToolCallAuditRecord:
    return AgentToolCallAuditRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        chat_session_id=row.chat_session_id,
        diagnostic_task_id=row.diagnostic_task_id,
        tool_name=row.tool_name,
        status=row.status,
        arguments=_json_dict(row.arguments),
        result_summary=row.result_summary,
        error_message=row.error_message,
        started_at=_ensure_utc(row.started_at),
        completed_at=_ensure_utc_optional(row.completed_at),
        duration_ms=row.duration_ms,
        created_at=_ensure_utc(row.created_at),
    )


def _graph_checkpoint_record(row: GraphCheckpointModel) -> GraphCheckpointRecord:
    return GraphCheckpointRecord(
        id=row.id,
        owner_user_id=row.owner_user_id,
        task_id=row.task_id,
        thread_id=row.thread_id,
        checkpoint_ns=row.checkpoint_ns,
        checkpoint_id=row.checkpoint_id,
        checkpoint_payload=_json_dict(row.checkpoint_payload),
        metadata=_json_dict(row.metadata_json),
        created_at=_ensure_utc(row.created_at),
    )


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _ensure_utc_optional(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _ensure_utc(value)
