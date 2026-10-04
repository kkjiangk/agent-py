"""SQLAlchemy ORM models for backend memory persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base metadata for memory ORM models."""


class UserModel(Base):
    """Persisted authenticated user."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class AuthSessionModel(Base):
    """Persisted revocable auth session."""

    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BackgroundJobModel(Base):
    """Durable owner-scoped background work item with a renewable lease."""

    __tablename__ = "background_jobs"
    __table_args__ = (
        Index("ix_background_jobs_status_available", "status", "available_at"),
        Index("ix_background_jobs_owner_created", "owner_user_id", "created_at"),
        Index("ix_background_jobs_resource", "owner_user_id", "resource_type", "resource_id"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    cancel_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retry_of_job_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BackgroundJobEventModel(Base):
    """Durable ordered event emitted by a background job."""

    __tablename__ = "background_job_events"
    __table_args__ = (
        UniqueConstraint("job_id", "sequence", name="uq_background_job_events_sequence"),
        Index("ix_background_job_events_owner_job_sequence", "owner_user_id", "job_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("background_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserFeedbackModel(Base):
    """Owner-scoped feedback for a supported product artifact."""

    __tablename__ = "user_feedback"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "target_type",
            "target_id",
            "subject_key",
            name="uq_user_feedback_target",
        ),
        Index("ix_user_feedback_owner_target", "owner_user_id", "target_type", "target_id"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(160), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    rating: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class McpConnectionModel(Base):
    """Owner-scoped MCP server connection configuration."""

    __tablename__ = "mcp_connections"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "name", name="uq_mcp_connections_owner_name"),
        Index("ix_mcp_connections_owner_updated", "owner_user_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    transport: Mapped[str] = mapped_column(String(40), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_check_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_tool_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_tools: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeDocumentModel(Base):
    """Persisted knowledge base document metadata."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        Index(
            "ix_knowledge_documents_owner_kb_uploaded_at",
            "owner_user_id",
            "knowledge_base_id",
            "uploaded_at",
        ),
        Index(
            "ix_knowledge_documents_owner_kb_hash",
            "owner_user_id",
            "knowledge_base_id",
            "content_hash",
        ),
        Index(
            "ix_knowledge_documents_owner_kb_document",
            "owner_user_id",
            "knowledge_base_id",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(160), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    index_status: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentIndexTaskModel(Base):
    """Persisted document indexing task attempt."""

    __tablename__ = "document_index_tasks"
    __table_args__ = (
        Index(
            "ix_document_index_tasks_owner_document_created_at",
            "owner_user_id",
            "knowledge_base_id",
            "document_id",
            "created_at",
        ),
        Index("ix_document_index_tasks_owner_status", "owner_user_id", "status"),
        Index("ix_document_index_tasks_retry_of", "retry_of_task_id"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    knowledge_base_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_of_task_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChatSessionModel(Base):
    """Persisted chat session."""

    __tablename__ = "chat_sessions"
    __table_args__ = (Index("ix_chat_sessions_owner_updated_at", "owner_user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(240), nullable=True)
    memory_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="every_30_turns")
    memory_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    compacted_message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    context_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_compacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class UserChatConfigurationModel(Base):
    """Persisted owner-scoped chat assembly selection."""

    __tablename__ = "user_chat_configurations"

    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    system_prompt_id: Mapped[str] = mapped_column(String(120), nullable=False)
    skill_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class UserChatPromptModel(Base):
    """Persisted owner-scoped editable system prompt."""

    __tablename__ = "user_chat_prompts"
    __table_args__ = (
        Index("ix_user_chat_prompts_owner_updated_at", "owner_user_id", "updated_at"),
        Index("ix_user_chat_prompts_owner_default", "owner_user_id", "is_default"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class UserChatSkillModel(Base):
    """Persisted owner-scoped uploaded Skill markdown file."""

    __tablename__ = "user_chat_skills"
    __table_args__ = (
        Index("ix_user_chat_skills_owner_updated_at", "owner_user_id", "updated_at"),
        Index("ix_user_chat_skills_owner_filename", "owner_user_id", "filename"),
        UniqueConstraint("owner_user_id", "name", name="uq_user_chat_skills_owner_name"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(240), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ChatMessageModel(Base):
    """Persisted chat message."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_session_created_at", "session_id", "created_at"),
        Index(
            "ix_chat_messages_owner_session_created_at",
            "owner_user_id",
            "session_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class AgentToolCallAuditModel(Base):
    """Persisted tenant-scoped Agent tool invocation audit entry."""

    __tablename__ = "tool_call_audits"
    __table_args__ = (
        CheckConstraint(
            "(chat_session_id IS NOT NULL AND diagnostic_task_id IS NULL) OR "
            "(chat_session_id IS NULL AND diagnostic_task_id IS NOT NULL)",
            name="ck_tool_call_audits_one_parent",
        ),
        Index(
            "ix_tool_call_audits_owner_session_created_at",
            "owner_user_id",
            "chat_session_id",
            "created_at",
        ),
        Index(
            "ix_tool_call_audits_owner_diagnostic_created_at",
            "owner_user_id",
            "diagnostic_task_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    chat_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    diagnostic_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("aiops_diagnostic_tasks.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class DiagnosticTaskModel(Base):
    """Persisted AIOps diagnostic task."""

    __tablename__ = "aiops_diagnostic_tasks"
    __table_args__ = (
        Index("ix_aiops_diagnostic_tasks_created_at", "created_at"),
        Index("ix_aiops_diagnostic_tasks_owner_created_at", "owner_user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DiagnosticReportModel(Base):
    """Persisted diagnostic report."""

    __tablename__ = "aiops_diagnostic_reports"
    __table_args__ = (
        Index("ix_aiops_diagnostic_reports_task_created_at", "task_id", "created_at"),
        Index(
            "ix_aiops_diagnostic_reports_owner_task_created_at",
            "owner_user_id",
            "task_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class DiagnosticCaseModel(Base):
    """Structured owner-scoped knowledge case created from a successful diagnosis."""

    __tablename__ = "aiops_diagnostic_cases"
    __table_args__ = (
        Index("ix_aiops_diagnostic_cases_owner_created_at", "owner_user_id", "created_at"),
        Index("ix_aiops_diagnostic_cases_owner_service", "owner_user_id", "service"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    report_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    index_task_id: Mapped[str] = mapped_column(
        ForeignKey("document_index_tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    alert_name: Mapped[str] = mapped_column(String(240), nullable=False)
    service: Mapped[str] = mapped_column(String(240), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    remediation: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class DiagnosticStepModel(Base):
    """Ordered plan and execution stage for an AIOps diagnostic."""

    __tablename__ = "aiops_diagnostic_steps"
    __table_args__ = (
        Index(
            "ix_aiops_diagnostic_steps_owner_task_sequence",
            "owner_user_id",
            "task_id",
            "sequence",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class DiagnosticEvidenceModel(Base):
    """Typed, immutable evidence produced by an AIOps diagnostic."""

    __tablename__ = "aiops_diagnostic_evidence"
    __table_args__ = (
        Index(
            "ix_aiops_diagnostic_evidence_owner_task_created_at",
            "owner_user_id",
            "task_id",
            "created_at",
        ),
        Index(
            "ix_aiops_diagnostic_evidence_owner_task_kind",
            "owner_user_id",
            "task_id",
            "kind",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[str | None] = mapped_column(
        ForeignKey("aiops_diagnostic_steps.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tool_call_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(240), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class ReportEvidenceLinkModel(Base):
    """Owner-scoped provenance edge from a diagnostic report to evidence."""

    __tablename__ = "aiops_report_evidence_links"
    __table_args__ = (
        Index(
            "ix_aiops_report_evidence_links_owner_report",
            "owner_user_id",
            "report_id",
        ),
        Index(
            "ix_aiops_report_evidence_links_owner_task_evidence",
            "owner_user_id",
            "task_id",
            "evidence_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    report_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_evidence.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class ToolCallAuditModel(Base):
    """Persisted tool call audit entry for a diagnostic task."""

    __tablename__ = "aiops_tool_call_audits"
    __table_args__ = (
        Index("ix_aiops_tool_call_audits_task_created_at", "task_id", "created_at"),
        Index(
            "ix_aiops_tool_call_audits_owner_task_created_at",
            "owner_user_id",
            "task_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class GraphCheckpointModel(Base):
    """Persisted LangGraph checkpoint for a diagnostic task."""

    __tablename__ = "aiops_graph_checkpoints"
    __table_args__ = (
        Index("ix_aiops_graph_checkpoints_task_thread", "task_id", "thread_id"),
        Index(
            "ix_aiops_graph_checkpoints_owner_task_thread",
            "owner_user_id",
            "task_id",
            "thread_id",
        ),
        Index(
            "ix_aiops_graph_checkpoints_identity",
            "thread_id",
            "checkpoint_ns",
            "checkpoint_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thread_id: Mapped[str] = mapped_column(String(160), nullable=False)
    checkpoint_ns: Mapped[str] = mapped_column(String(160), nullable=False)
    checkpoint_id: Mapped[str] = mapped_column(String(160), nullable=False)
    checkpoint_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class RemediationApprovalModel(Base):
    """Owner-scoped human decision gate for remediation commands."""

    __tablename__ = "aiops_remediation_approvals"
    __table_args__ = (
        Index(
            "ix_aiops_remediation_approvals_owner_task_created",
            "owner_user_id",
            "task_id",
            "created_at",
        ),
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high', 'critical')",
            name="ck_aiops_remediation_approvals_risk",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name="ck_aiops_remediation_approvals_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("aiops_diagnostic_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by_user_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatch_status: Mapped[str] = mapped_column(String(20), nullable=False)
    dispatch_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatch_lease_owner: Mapped[str | None] = mapped_column(String(80), nullable=True)
    dispatch_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
