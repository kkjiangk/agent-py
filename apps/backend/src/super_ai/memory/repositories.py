"""Business-facing memory repository contracts and records."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

ChatMemoryMode = str

JsonDict = dict[str, object]


@dataclass(frozen=True, slots=True)
class TimeRangeFilter:
    """Inclusive timestamp range for history queries."""

    start_at: datetime | None = None
    end_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ChatSessionRecord:
    id: str
    owner_user_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    memory_mode: ChatMemoryMode = "every_30_turns"
    memory_summary: str | None = None
    compacted_message_count: int = 0
    context_tokens: int = 0
    last_compacted_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ChatMessageRecord:
    id: str
    owner_user_id: str
    session_id: str
    role: str
    content: str
    metadata: JsonDict
    created_at: datetime


@dataclass(frozen=True, slots=True)
class UserChatConfigurationRecord:
    owner_user_id: str
    system_prompt_id: str
    skill_ids: list[str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class UserChatPromptRecord:
    id: str
    owner_user_id: str
    label: str
    content: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class UserChatSkillRecord:
    id: str
    owner_user_id: str
    filename: str
    name: str
    description: str
    content: str
    size_bytes: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class KnowledgeDocumentRecord:
    id: str
    owner_user_id: str
    knowledge_base_id: str
    filename: str
    size_bytes: int
    mime_type: str
    content_hash: str
    status: str
    index_status: str
    metadata: JsonDict
    uploaded_at: datetime
    updated_at: datetime
    source: str | None
    deleted_at: datetime | None


@dataclass(frozen=True, slots=True)
class DocumentIndexTaskRecord:
    id: str
    owner_user_id: str
    knowledge_base_id: str
    document_id: str
    status: str
    failure_reason: str | None
    retry_of_task_id: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class DiagnosticTaskRecord:
    id: str
    owner_user_id: str
    status: str
    query: str
    input_payload: JsonDict
    result_payload: JsonDict
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class DiagnosticReportRecord:
    id: str
    owner_user_id: str
    task_id: str
    title: str
    content: str
    payload: JsonDict
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DiagnosticCaseRecord:
    id: str
    owner_user_id: str
    task_id: str
    report_id: str
    document_id: str
    index_task_id: str
    alert_name: str
    service: str
    keywords: list[str]
    root_cause: str
    remediation: str
    summary: str
    evidence_ids: list[str]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DiagnosticStepRecord:
    id: str
    owner_user_id: str
    task_id: str
    sequence: int
    phase: str
    status: str
    payload: JsonDict
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DiagnosticEvidenceRecord:
    id: str
    owner_user_id: str
    task_id: str
    step_id: str | None
    tool_call_id: str | None
    kind: str
    source: str
    summary: str
    payload: JsonDict
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ReportEvidenceLinkRecord:
    id: str
    owner_user_id: str
    task_id: str
    report_id: str
    evidence_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ToolCallAuditRecord:
    id: str
    owner_user_id: str
    task_id: str
    tool_name: str
    status: str
    arguments: JsonDict
    result_payload: JsonDict
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AgentToolCallAuditRecord:
    """A tenant-scoped Agent tool invocation audit entry."""

    id: str
    owner_user_id: str
    chat_session_id: str | None
    diagnostic_task_id: str | None
    tool_name: str
    status: str
    arguments: JsonDict
    result_summary: str | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class GraphCheckpointRecord:
    id: str
    owner_user_id: str
    task_id: str
    thread_id: str
    checkpoint_ns: str
    checkpoint_id: str
    checkpoint_payload: JsonDict
    metadata: JsonDict
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RemediationApprovalRecord:
    id: str
    owner_user_id: str
    task_id: str
    tool_name: str
    arguments: JsonDict
    rationale: str
    risk_level: str
    status: str
    decision_note: str | None
    decided_by_user_id: str | None
    decided_at: datetime | None
    dispatch_status: str
    dispatch_error: str | None
    dispatched_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class BackgroundJobRecord:
    id: str
    owner_user_id: str
    kind: str
    resource_type: str
    resource_id: str
    status: str
    payload: JsonDict
    attempt: int
    max_attempts: int
    timeout_seconds: int
    available_at: datetime
    lease_owner: str | None
    lease_expires_at: datetime | None
    cancel_requested_at: datetime | None
    retry_of_job_id: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class BackgroundJobEventRecord:
    id: str
    job_id: str
    owner_user_id: str
    sequence: int
    payload: JsonDict
    created_at: datetime


@dataclass(frozen=True, slots=True)
class UserFeedbackRecord:
    id: str
    owner_user_id: str
    target_type: str
    target_id: str
    subject_id: str | None
    rating: str
    reason: str | None
    comment: str | None
    correction: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class McpConnectionRecord:
    id: str
    owner_user_id: str
    name: str
    transport: str
    url: str
    enabled: bool
    timeout_seconds: int
    retries: int
    last_check_ok: bool | None
    last_tool_count: int | None
    last_tools: list[JsonDict]
    last_error: str | None
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TenantScopeError(PermissionError):
    """Raised when a scoped repository operation crosses tenant boundaries."""


class ChatMemoryRepository(Protocol):
    """Repository contract for chat memory."""

    async def create_session(
        self,
        *,
        owner_user_id: str,
        session_id: str,
        title: str | None = None,
        created_at: datetime | None = None,
    ) -> ChatSessionRecord:
        """Create a chat session record."""
        ...

    async def get_session(
        self,
        *,
        owner_user_id: str,
        session_id: str,
    ) -> ChatSessionRecord | None:
        """Get a chat session by id within the owner scope."""
        ...

    async def update_session_title(
        self,
        *,
        owner_user_id: str,
        session_id: str,
        title: str,
        updated_at: datetime | None = None,
    ) -> ChatSessionRecord | None:
        """Update a chat session title within the owner scope."""
        ...

    async def update_memory_state(
        self,
        *,
        owner_user_id: str,
        session_id: str,
        memory_mode: ChatMemoryMode | None = None,
        memory_summary: str | None = None,
        compacted_message_count: int | None = None,
        context_tokens: int | None = None,
        last_compacted_at: datetime | None = None,
        clear_compaction: bool = False,
        updated_at: datetime | None = None,
    ) -> ChatSessionRecord | None:
        """Update owner-scoped memory policy and compaction state."""
        ...

    async def list_sessions(
        self,
        *,
        owner_user_id: str,
        time_range: TimeRangeFilter | None = None,
    ) -> list[ChatSessionRecord]:
        """List chat sessions by owner and optional time range."""
        ...

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
        """Append a message to an existing chat session."""
        ...

    async def clear_messages(
        self,
        *,
        owner_user_id: str,
        session_id: str,
        updated_at: datetime | None = None,
    ) -> int:
        """Delete messages for a scoped session and return the number deleted."""
        ...

    async def delete_session(
        self,
        *,
        owner_user_id: str,
        session_id: str,
    ) -> bool:
        """Delete a scoped chat session and its messages."""
        ...

    async def list_messages(
        self,
        *,
        owner_user_id: str,
        session_id: str,
        time_range: TimeRangeFilter | None = None,
    ) -> list[ChatMessageRecord]:
        """List chat messages by session and optional time range."""
        ...

    async def get_message(
        self,
        *,
        owner_user_id: str,
        message_id: str,
    ) -> ChatMessageRecord | None:
        """Get one message by id within the owner scope."""
        ...


class UserChatConfigurationRepository(Protocol):
    """Repository contract for owner-scoped chat prompt and Skill choices."""

    async def get_or_create(
        self, *, owner_user_id: str, system_prompt_id: str, skill_ids: list[str]
    ) -> UserChatConfigurationRecord: ...

    async def update(
        self, *, owner_user_id: str, system_prompt_id: str, skill_ids: list[str]
    ) -> UserChatConfigurationRecord: ...


class UserChatPromptRepository(Protocol):
    """Repository contract for owner-scoped editable system prompts."""

    async def ensure_default(
        self,
        *,
        owner_user_id: str,
        label: str,
        content: str,
    ) -> UserChatPromptRecord:
        """Return or create the owner's default system prompt."""
        ...

    async def create(
        self,
        *,
        owner_user_id: str,
        prompt_id: str,
        label: str,
        content: str,
        is_default: bool = False,
    ) -> UserChatPromptRecord:
        """Create a prompt in the owner scope."""
        ...

    async def get(
        self,
        *,
        owner_user_id: str,
        prompt_id: str,
    ) -> UserChatPromptRecord | None:
        """Get a prompt by id within the owner scope."""
        ...

    async def list(self, *, owner_user_id: str) -> list[UserChatPromptRecord]:
        """List prompts within the owner scope."""
        ...

    async def update(
        self,
        *,
        owner_user_id: str,
        prompt_id: str,
        label: str,
        content: str,
    ) -> UserChatPromptRecord | None:
        """Update a prompt within the owner scope."""
        ...

    async def delete(self, *, owner_user_id: str, prompt_id: str) -> bool:
        """Delete a prompt within the owner scope."""
        ...


class UserChatSkillRepository(Protocol):
    """Repository contract for owner-scoped uploaded Skill files."""

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
        """Create a Skill file record in the owner scope."""
        ...

    async def get(
        self,
        *,
        owner_user_id: str,
        skill_id: str,
    ) -> UserChatSkillRecord | None:
        """Get a Skill file by id within the owner scope."""
        ...

    async def list(self, *, owner_user_id: str) -> list[UserChatSkillRecord]:
        """List Skill files within the owner scope."""
        ...

    async def delete(self, *, owner_user_id: str, skill_id: str) -> bool:
        """Delete a Skill file within the owner scope."""
        ...


class KnowledgeDocumentRepository(Protocol):
    async def lexical_revision(
        self, *, owner_user_id: str, knowledge_base_ids: Sequence[str]
    ) -> str:
        """Version only scoped document metadata without loading document bodies."""
        ...

    """Repository contract for user-owned knowledge document metadata."""

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
        """Create document metadata in an owner scope."""
        ...

    async def get_document(
        self,
        *,
        owner_user_id: str,
        knowledge_base_id: str,
        document_id: str,
        include_deleted: bool = False,
    ) -> KnowledgeDocumentRecord | None:
        """Get a document by id within the owner and knowledge-base scope."""
        ...

    async def list_documents(
        self,
        *,
        owner_user_id: str,
        knowledge_base_id: str,
        time_range: TimeRangeFilter | None = None,
        include_deleted: bool = False,
    ) -> list[KnowledgeDocumentRecord]:
        """List document metadata by owner, knowledge base, and optional time range."""
        ...

    async def find_active_by_hash(
        self,
        *,
        owner_user_id: str,
        knowledge_base_id: str,
        content_hash: str,
    ) -> KnowledgeDocumentRecord | None:
        """Find an active document by scoped content hash."""
        ...

    async def mark_document_deleted(
        self,
        *,
        owner_user_id: str,
        knowledge_base_id: str,
        document_id: str,
        deleted_at: datetime | None = None,
    ) -> KnowledgeDocumentRecord | None:
        """Mark a scoped document deleted."""
        ...

    async def update_index_status(
        self,
        *,
        owner_user_id: str,
        knowledge_base_id: str,
        document_id: str,
        index_status: str,
        updated_at: datetime | None = None,
    ) -> KnowledgeDocumentRecord | None:
        """Update a scoped document's latest index status."""
        ...


class DocumentIndexTaskRepository(Protocol):
    """Repository contract for user-owned document index task attempts."""

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
        """Create a document index task attempt."""
        ...

    async def create_retry(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        retry_of_task_id: str,
        created_at: datetime | None = None,
    ) -> DocumentIndexTaskRecord:
        """Create a retry attempt linked to a prior task in the same owner scope."""
        ...

    async def get_task(
        self,
        *,
        owner_user_id: str,
        task_id: str,
    ) -> DocumentIndexTaskRecord | None:
        """Get a document index task by id within the owner scope."""
        ...

    async def list_tasks_for_document(
        self,
        *,
        owner_user_id: str,
        knowledge_base_id: str,
        document_id: str,
    ) -> list[DocumentIndexTaskRecord]:
        """List index tasks for a scoped document."""
        ...

    async def mark_running(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        started_at: datetime | None = None,
    ) -> DocumentIndexTaskRecord | None:
        """Mark a task running."""
        ...

    async def mark_succeeded(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        completed_at: datetime | None = None,
    ) -> DocumentIndexTaskRecord | None:
        """Mark a task succeeded."""
        ...

    async def mark_failed(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        failure_reason: str,
        completed_at: datetime | None = None,
    ) -> DocumentIndexTaskRecord | None:
        """Mark a task failed with a safe reason."""
        ...

    async def mark_cancelled(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        completed_at: datetime | None = None,
    ) -> DocumentIndexTaskRecord | None:
        """Mark a task cancelled within the owner scope."""
        ...


class DiagnosticMemoryRepository(Protocol):
    """Repository contract for AIOps diagnostic memory."""

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
        """Create a diagnostic task."""
        ...

    async def get_task(
        self,
        *,
        owner_user_id: str,
        task_id: str,
    ) -> DiagnosticTaskRecord | None:
        """Get a diagnostic task by id within the owner scope."""
        ...

    async def update_task(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        status: str,
        result_payload: JsonDict | None = None,
        completed_at: datetime | None = None,
    ) -> DiagnosticTaskRecord | None:
        """Update task state and optional evidence-backed result payload."""
        ...

    async def list_tasks(
        self,
        *,
        owner_user_id: str,
        time_range: TimeRangeFilter | None = None,
    ) -> list[DiagnosticTaskRecord]:
        """List diagnostic tasks by optional time range."""
        ...

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
        """Add a diagnostic report."""
        ...

    async def list_reports(
        self,
        *,
        owner_user_id: str,
        task_id: str,
    ) -> list[DiagnosticReportRecord]:
        """List diagnostic reports by task."""
        ...

    async def get_report(
        self,
        *,
        owner_user_id: str,
        report_id: str,
    ) -> DiagnosticReportRecord | None:
        """Get one diagnostic report within the owner scope."""
        ...

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
        """Create one structured case for an owned successful task."""
        ...

    async def get_case_for_task(
        self,
        *,
        owner_user_id: str,
        task_id: str,
    ) -> DiagnosticCaseRecord | None:
        """Get the owner-scoped structured case for one task."""
        ...

    async def get_case(
        self,
        *,
        owner_user_id: str,
        case_id: str,
    ) -> DiagnosticCaseRecord | None:
        """Get one structured diagnosis case only within the owner's scope."""
        ...

    async def list_cases(self, *, owner_user_id: str) -> list[DiagnosticCaseRecord]:
        """List structured diagnosis cases newest first within owner scope."""
        ...

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
        """Store one ordered diagnostic graph stage within owner scope."""
        ...

    async def list_steps(
        self,
        *,
        owner_user_id: str,
        task_id: str,
    ) -> list[DiagnosticStepRecord]:
        """List ordered diagnostic graph stages within owner scope."""
        ...

    async def get_step(
        self,
        *,
        owner_user_id: str,
        step_id: str,
    ) -> DiagnosticStepRecord | None:
        """Get one diagnostic step within the owner scope."""
        ...

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
        """Store typed diagnostic evidence within owner scope."""
        ...

    async def list_evidence(
        self,
        *,
        owner_user_id: str,
        task_id: str,
    ) -> list[DiagnosticEvidenceRecord]:
        """List typed diagnostic evidence within owner scope."""
        ...

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
        """Persist a report provenance link after validating owner and task scope."""
        ...

    async def list_report_evidence_links(
        self,
        *,
        owner_user_id: str,
        task_id: str,
    ) -> list[ReportEvidenceLinkRecord]:
        """List report provenance links within owner scope."""
        ...

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
        """Add a tool call audit entry."""
        ...

    async def list_tool_call_audits(
        self,
        *,
        owner_user_id: str,
        task_id: str,
    ) -> list[ToolCallAuditRecord]:
        """List tool call audit entries by task."""
        ...

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
        """Persist a diagnostic LangGraph checkpoint."""
        ...

    async def list_checkpoints(
        self,
        *,
        owner_user_id: str,
        task_id: str,
    ) -> list[GraphCheckpointRecord]:
        """List graph checkpoints by diagnostic task."""
        ...


class ToolCallAuditRepository(Protocol):
    """Repository contract for tenant-scoped Agent tool audits."""

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
        """Create an in-progress audit associated with an owned chat session."""
        ...

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
        """Create an in-progress audit associated with an owned diagnostic task."""
        ...

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
        """Finalize a scoped audit and derive its elapsed duration."""
        ...

    async def list_for_chat_session(
        self,
        *,
        owner_user_id: str,
        chat_session_id: str,
    ) -> list[AgentToolCallAuditRecord]:
        """List audits for an owned chat session in chronological order."""
        ...

    async def list_for_diagnostic_task(
        self,
        *,
        owner_user_id: str,
        diagnostic_task_id: str,
    ) -> list[AgentToolCallAuditRecord]:
        """List audits for an owned diagnostic task in chronological order."""
        ...


class BackgroundJobRepository(Protocol):
    """Repository contract for durable leased jobs and their event log."""

    async def enqueue(
        self,
        *,
        owner_user_id: str,
        job_id: str,
        kind: str,
        resource_type: str,
        resource_id: str,
        payload: JsonDict | None = None,
        max_attempts: int = 3,
        timeout_seconds: int = 900,
        retry_of_job_id: str | None = None,
        available_at: datetime | None = None,
    ) -> BackgroundJobRecord: ...

    async def get(self, *, owner_user_id: str, job_id: str) -> BackgroundJobRecord | None: ...

    async def find_for_resource(
        self,
        *,
        owner_user_id: str,
        resource_type: str,
        resource_id: str,
    ) -> BackgroundJobRecord | None: ...

    async def list(self, *, owner_user_id: str) -> list[BackgroundJobRecord]: ...

    async def claim_next(
        self,
        *,
        worker_id: str,
        lease_expires_at: datetime,
        now: datetime | None = None,
    ) -> BackgroundJobRecord | None: ...

    async def renew_lease(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_expires_at: datetime,
    ) -> bool: ...

    async def append_event(
        self,
        *,
        owner_user_id: str,
        job_id: str,
        payload: JsonDict,
    ) -> BackgroundJobEventRecord: ...

    async def list_events(
        self,
        *,
        owner_user_id: str,
        job_id: str,
        after_sequence: int = 0,
    ) -> list[BackgroundJobEventRecord]: ...

    async def request_cancel(
        self, *, owner_user_id: str, job_id: str
    ) -> BackgroundJobRecord | None: ...

    async def mark_succeeded(
        self, *, job_id: str, worker_id: str
    ) -> BackgroundJobRecord | None: ...

    async def mark_cancelled(
        self, *, job_id: str, worker_id: str
    ) -> BackgroundJobRecord | None: ...

    async def handle_failure(
        self,
        *,
        job_id: str,
        worker_id: str,
        error_message: str,
        retry_at: datetime,
    ) -> BackgroundJobRecord | None: ...

    async def retry(
        self,
        *,
        owner_user_id: str,
        source_job_id: str,
        new_job_id: str,
    ) -> BackgroundJobRecord | None: ...


class UserFeedbackRepository(Protocol):
    """Repository contract for owner-scoped polymorphic feedback."""

    async def upsert(
        self,
        *,
        owner_user_id: str,
        feedback_id: str,
        target_type: str,
        target_id: str,
        subject_id: str | None,
        rating: str,
        reason: str | None,
        comment: str | None,
        correction: str | None,
    ) -> UserFeedbackRecord: ...

    async def list_for_target(
        self,
        *,
        owner_user_id: str,
        target_type: str,
        target_id: str,
    ) -> list[UserFeedbackRecord]: ...

    async def delete(self, *, owner_user_id: str, feedback_id: str) -> bool: ...


class McpConnectionRepository(Protocol):
    """Repository contract for owner-scoped MCP server configurations."""

    async def create(
        self,
        *,
        owner_user_id: str,
        connection_id: str,
        name: str,
        transport: str,
        url: str,
        enabled: bool,
        timeout_seconds: int,
        retries: int,
    ) -> McpConnectionRecord: ...

    async def get(
        self, *, owner_user_id: str, connection_id: str
    ) -> McpConnectionRecord | None: ...

    async def list(self, *, owner_user_id: str) -> list[McpConnectionRecord]: ...

    async def update(
        self,
        *,
        owner_user_id: str,
        connection_id: str,
        name: str,
        transport: str,
        url: str,
        enabled: bool,
        timeout_seconds: int,
        retries: int,
    ) -> McpConnectionRecord | None: ...

    async def save_check(
        self,
        *,
        owner_user_id: str,
        connection_id: str,
        ok: bool,
        tools: list[JsonDict],
        error: str | None,
    ) -> McpConnectionRecord | None: ...

    async def delete(self, *, owner_user_id: str, connection_id: str) -> bool: ...


class RemediationApprovalRepository(Protocol):
    """Repository contract for owner-scoped human remediation decisions."""

    async def create(
        self,
        *,
        owner_user_id: str,
        approval_id: str,
        task_id: str,
        tool_name: str,
        arguments: JsonDict,
        rationale: str,
        risk_level: str,
    ) -> RemediationApprovalRecord: ...

    async def get(
        self, *, owner_user_id: str, approval_id: str
    ) -> RemediationApprovalRecord | None: ...

    async def list_for_task(
        self, *, owner_user_id: str, task_id: str
    ) -> list[RemediationApprovalRecord]: ...

    async def transition_pending(
        self,
        *,
        owner_user_id: str,
        approval_id: str,
        status: str,
        decided_by_user_id: str,
        decision_note: str | None,
    ) -> RemediationApprovalRecord | None: ...

    async def update_dispatch(
        self,
        *,
        owner_user_id: str,
        approval_id: str,
        dispatch_status: str,
        dispatch_error: str | None,
    ) -> RemediationApprovalRecord | None: ...

    async def claim_dispatch(
        self,
        *,
        owner_user_id: str,
        approval_id: str,
        lease_owner: str,
        lease_expires_at: datetime,
        now: datetime,
    ) -> RemediationApprovalRecord | None: ...

    async def finish_dispatch(
        self,
        *,
        owner_user_id: str,
        approval_id: str,
        lease_owner: str,
        dispatch_status: str,
        dispatch_error: str | None,
    ) -> RemediationApprovalRecord | None: ...


@dataclass(frozen=True, slots=True)
class MemoryRepositories:
    """Repository bundle for dependency injection."""

    chat: ChatMemoryRepository
    documents: KnowledgeDocumentRepository
    document_index_tasks: DocumentIndexTaskRepository
    diagnostics: DiagnosticMemoryRepository
    tool_call_audits: ToolCallAuditRepository | None = None
    chat_configurations: UserChatConfigurationRepository | None = None
    chat_prompts: UserChatPromptRepository | None = None
    chat_skills: UserChatSkillRepository | None = None
    background_jobs: BackgroundJobRepository | None = None
    feedback: UserFeedbackRepository | None = None
    mcp_connections: McpConnectionRepository | None = None
    remediation_approvals: RemediationApprovalRepository | None = None
