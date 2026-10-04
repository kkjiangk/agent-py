"""FastAPI application with user authentication routes."""
# pyright: reportUnusedFunction=false

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
from time import monotonic
from typing import Annotated, Protocol, cast
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from super_ai.aiops import AiopsDiagnosticService, DiagnosisCasePersistor
from super_ai.alerts import (
    ActiveAlert,
    ActiveAlertProvider,
    AlertProviderError,
    build_alertmanager_alert_provider,
)
from super_ai.auth.repositories import UserRecord
from super_ai.auth.service import AuthService
from super_ai.auth.sqlite import SQLiteAuthRepository
from super_ai.chat import (
    ChatAgentRunner,
    ChatStreamingService,
    LangChainChatAgentRunner,
    encode_sse,
)
from super_ai.chat.configuration import (
    DEFAULT_CHAT_PROMPT_CONTENT,
    DEFAULT_CHAT_PROMPT_LABEL,
    validate_chat_prompt_content,
    validate_skill_upload,
)
from super_ai.chat.memory import (
    SUPPORTED_CHAT_MEMORY_MODES,
    ChatContextLimitReached,
    ChatMemoryService,
    memory_payload,
)
from super_ai.documents import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DOCUMENT_MAX_SIZE_BYTES,
    MARKDOWN_DOCUMENT_MIME_TYPES,
    PDF_DOCUMENT_MIME_TYPES,
    DocumentIndexingService,
    chunk_document_text,
    extract_indexable_text,
)
from super_ai.error_catalog import ERROR_DEFINITIONS
from super_ai.events import (
    AlertEvent,
    AlertGatewayService,
    BrokerUnavailableError,
    EventIngestionSettings,
    EventPublisher,
    KafkaEventPublisher,
    RedisWorkflowCheckpointStore,
    WorkflowCheckpointStore,
    load_event_ingestion_settings,
)
from super_ai.feedback import FeedbackError, UserFeedbackService
from super_ai.foundation import get_foundation_info
from super_ai.jobs import BackgroundJobContext, BackgroundJobRuntime, JobCancelled
from super_ai.llm import (
    EmbeddingModel,
    LlmProvider,
    RerankModel,
    build_default_llm_provider,
    load_llm_provider_config,
)
from super_ai.mcp_client import LocalMcpClient
from super_ai.mcp_connections import McpConnectionError, McpConnectionService
from super_ai.memory.database import (
    create_memory_engine,
    create_memory_session_factory,
    load_memory_database_settings,
)
from super_ai.memory.repositories import (
    AgentToolCallAuditRecord,
    BackgroundJobRecord,
    BackgroundJobRepository,
    ChatMessageRecord,
    ChatSessionRecord,
    DiagnosticCaseRecord,
    DiagnosticEvidenceRecord,
    DiagnosticReportRecord,
    DiagnosticStepRecord,
    DiagnosticTaskRecord,
    DocumentIndexTaskRecord,
    GraphCheckpointRecord,
    KnowledgeDocumentRecord,
    McpConnectionRecord,
    MemoryRepositories,
    RemediationApprovalRecord,
    RemediationApprovalRepository,
    ReportEvidenceLinkRecord,
    TimeRangeFilter,
    UserChatConfigurationRecord,
    UserChatConfigurationRepository,
    UserChatPromptRecord,
    UserChatPromptRepository,
    UserChatSkillRecord,
    UserChatSkillRepository,
    UserFeedbackRecord,
)
from super_ai.memory.sqlite import create_sqlite_memory_repositories
from super_ai.observability import (
    configure_structured_logging,
    elapsed_ms,
    emit_event,
    reset_request_id,
    set_request_id,
)
from super_ai.project_config import project_config_section, required_int, required_str
from super_ai.remediation import RemediationApprovalService, RemediationDecisionError
from super_ai.retrieval import KnowledgeRetrievalTool, RetrievalVectorStore
from super_ai.retrieval.cache import LexicalIndexCache
from super_ai.telemetry import configure_telemetry
from super_ai.vector_store import (
    MilvusHealthCheckResult,
    VectorChunkRecord,
    build_default_milvus_vector_store,
    load_milvus_vector_store_settings,
)

from .auth import auth_router, current_user
from .observability import RequestMetrics
from .responses import ApiErrorException, error_response, success_response
from .schemas import (
    AppendChatMessageRequest,
    CreateAiopsDiagnosticRequest,
    CreateChatPromptRequest,
    CreateChatSessionRequest,
    CreateRemediationApprovalRequest,
    DecideRemediationApprovalRequest,
    McpConnectionMutationRequest,
    StreamChatMessageRequest,
    UpdateChatAssemblyConfigurationRequest,
    UpdateChatMemoryRequest,
    UpdateChatPromptRequest,
    UpsertFeedbackRequest,
)

logger = logging.getLogger(__name__)


class AiopsDiagnosticRunner(Protocol):
    def stream(
        self,
        *,
        task: DiagnosticTaskRecord,
        accessible_knowledge_base_ids: Sequence[str],
    ) -> AsyncIterator[dict[str, object]]:
        """Stream one persisted AIOps diagnostic execution."""
        ...


class MilvusHealthCheckProvider(Protocol):
    def health_check(self) -> MilvusHealthCheckResult:
        """Return Milvus readiness/config status."""
        ...


class DocumentVectorStoreProvider(MilvusHealthCheckProvider, Protocol):
    def initialize(self) -> None:
        """Ensure vector collection/indexes exist before document writes."""
        ...

    def delete_document_chunks(
        self,
        *,
        tenant_id: str,
        knowledge_base_id: str,
        document_id: str,
    ) -> None:
        """Delete Milvus chunks for a scoped document."""
        ...

    def insert_chunks(self, chunks: Sequence[VectorChunkRecord]) -> None:
        """Insert Milvus chunks for document indexing."""
        ...


class DocumentIndexTaskScheduler(Protocol):
    def schedule(self, *, owner_user_id: str, task_id: str) -> Awaitable[None] | None:
        """Schedule a persisted index task without blocking the request."""
        ...


class DurableDocumentIndexTaskScheduler:
    """Enqueue document indexing in the durable background runtime."""

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def schedule(self, *, owner_user_id: str, task_id: str) -> None:
        repository = _background_job_repository_from_app(self._app)
        existing = await repository.find_for_resource(
            owner_user_id=owner_user_id,
            resource_type="document_index_task",
            resource_id=task_id,
        )
        if existing is None:
            await repository.enqueue(
                owner_user_id=owner_user_id,
                job_id=f"job_{uuid4().hex}",
                kind="document_index",
                resource_type="document_index_task",
                resource_id=task_id,
                payload={"taskId": task_id},
                max_attempts=3,
                timeout_seconds=900,
            )
        await _background_job_runtime_from_app(self._app).start()


def create_app(
    *,
    database_url: str | None = None,
    project_config_path: str | Path | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    vector_store: MilvusHealthCheckProvider | None = None,
    embedding_model: EmbeddingModel | None = None,
    rerank_model: RerankModel | None = None,
    llm_provider: LlmProvider | None = None,
    chat_agent_runner: ChatAgentRunner | None = None,
    aiops_diagnostic_runner: AiopsDiagnosticRunner | None = None,
    alert_provider: ActiveAlertProvider | None = None,
    alert_event_publisher: EventPublisher | None = None,
    workflow_checkpoint_store: WorkflowCheckpointStore | None = None,
    index_task_scheduler: DocumentIndexTaskScheduler | None = None,
) -> FastAPI:
    """Create the backend API application."""
    resolved_project_config_path = (
        str(project_config_path) if project_config_path is not None else None
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
        runtime = cast(BackgroundJobRuntime, application.state.background_job_runtime)
        await runtime.start()
        try:
            yield
        finally:
            await runtime.stop()
            event_publisher = cast(EventPublisher | None, application.state.alert_event_publisher)
            if event_publisher is not None:
                await event_publisher.close()
            checkpoint_store = cast(
                WorkflowCheckpointStore | None,
                application.state.workflow_checkpoint_store,
            )
            if checkpoint_store is not None:
                await checkpoint_store.close()
            owned_engine = cast(AsyncEngine | None, application.state.memory_engine)
            if owned_engine is not None:
                await owned_engine.dispose()

    configure_structured_logging()
    configure_telemetry(config_path=resolved_project_config_path)
    app = FastAPI(title="Super AI API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    engine: AsyncEngine | None = None
    if session_factory is None:
        engine = create_memory_engine(database_url, config_path=resolved_project_config_path)
        session_factory = create_memory_session_factory(engine)
    app.state.project_config_path = resolved_project_config_path
    app.state.memory_engine = engine
    app.state.memory_session_factory = session_factory
    app.state.auth_service = AuthService(SQLiteAuthRepository(session_factory))
    repositories = create_sqlite_memory_repositories(session_factory)
    app.state.memory_repositories = repositories
    app.state.vector_store = vector_store or build_default_milvus_vector_store(
        config_path=resolved_project_config_path
    )
    app.state.embedding_model = embedding_model
    app.state.rerank_model = rerank_model
    app.state.llm_provider = llm_provider
    app.state.chat_agent_runner = chat_agent_runner
    app.state.aiops_diagnostic_runner = aiops_diagnostic_runner
    app.state.alert_provider = alert_provider
    app.state.alert_event_publisher = alert_event_publisher
    app.state.event_ingestion_settings = None
    app.state.workflow_checkpoint_store = workflow_checkpoint_store
    if repositories.background_jobs is None:
        raise RuntimeError("Background job repository is required.")
    background_runtime = BackgroundJobRuntime(repositories.background_jobs)
    background_runtime.register("document_index", _document_index_job_handler(app))
    background_runtime.register("aiops_diagnosis", _aiops_job_handler(app))
    background_runtime.register("remediation_dispatch", _remediation_job_handler(app))
    app.state.background_job_runtime = background_runtime
    app.state.index_task_scheduler = index_task_scheduler or DurableDocumentIndexTaskScheduler(app)
    app.state.request_metrics = RequestMetrics()
    app.state.lexical_index_cache = LexicalIndexCache()

    @app.middleware("http")
    async def observe_request(request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or f"req_{uuid4().hex}"
        request.state.request_id = request_id
        correlation_token = set_request_id(request_id)
        started_at = monotonic()
        response: Response | None = None
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as exc:
            emit_event(logger, "request.error", errorCategory=exc.__class__.__name__)
            raise
        finally:
            status_code = response.status_code if response is not None else 500
            latency_ms = elapsed_ms(started_at)
            app.state.request_metrics.record(latency_ms=latency_ms, status_code=status_code)
            emit_event(
                logger,
                "request.complete",
                method=request.method,
                path=request.url.path,
                status=status_code,
                latencyMs=latency_ms,
            )
            reset_request_id(correlation_token)

    @app.exception_handler(ApiErrorException)
    async def handle_api_error(request: Request, exc: ApiErrorException) -> object:
        emit_event(logger, "request.error", errorCode=exc.code)
        return error_response(request, exc.code, message=exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, _exc: RequestValidationError) -> object:
        emit_event(logger, "request.error", errorCode="VALIDATION_INVALID_ARGUMENT")
        return error_response(request, "VALIDATION_INVALID_ARGUMENT")

    @app.get("/health")
    async def health(request: Request) -> object:
        foundation = get_foundation_info()
        return success_response(
            request,
            {
                "service": foundation.service,
                "status": foundation.status,
                "version": foundation.version,
            },
        )

    @app.get("/metrics")
    async def metrics(request: Request) -> object:
        snapshot = request.app.state.request_metrics.snapshot()
        average = (
            snapshot.total_latency_ms / snapshot.request_count if snapshot.request_count else 0.0
        )
        return success_response(
            request,
            {
                "requestCount": snapshot.request_count,
                "failureCount": snapshot.failure_count,
                "averageLatencyMs": round(average, 3),
            },
        )

    @app.get("/health/mcp")
    async def mcp_health(request: Request) -> object:
        result = await _mcp_client(request).readiness()
        return success_response(request, result, status_code=200 if result["ok"] else 503)

    @app.get("/ready")
    async def ready(request: Request) -> object:
        dependencies = await _runtime_dependency_payload(request)
        is_ready = all(bool(component["ok"]) for component in dependencies.values())
        return success_response(
            request,
            {"status": "ready" if is_ready else "degraded", "dependencies": dependencies},
            status_code=200 if is_ready else 503,
        )

    @app.get("/config/check")
    async def config_check(request: Request) -> object:
        configuration = _configuration_check_payload(request)
        dependencies = await _runtime_dependency_payload(request)
        is_valid = all(bool(component["valid"]) for component in configuration.values())
        is_ready = all(bool(component["ok"]) for component in dependencies.values())
        return success_response(
            request,
            {
                "status": "ready" if is_valid and is_ready else "degraded",
                "configuration": configuration,
                "dependencies": dependencies,
            },
            status_code=200 if is_valid and is_ready else 503,
        )

    app.include_router(auth_router)

    @app.get("/background-jobs")
    async def list_background_jobs(
        request: Request,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        jobs = await _background_job_repository(request).list(owner_user_id=user.id)
        return success_response(request, {"items": [_background_job_payload(job) for job in jobs]})

    @app.get("/background-jobs/{job_id}")
    async def get_background_job(
        request: Request,
        job_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        job = await _background_job_repository(request).get(
            owner_user_id=user.id,
            job_id=job_id,
        )
        if job is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, _background_job_payload(job))

    @app.post("/background-jobs/{job_id}:cancel")
    async def cancel_background_job(
        request: Request,
        job_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        job = await _background_job_repository(request).request_cancel(
            owner_user_id=user.id,
            job_id=job_id,
        )
        if job is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        await _cancel_background_resource(request, job)
        return success_response(request, _background_job_payload(job))

    @app.post("/background-jobs/{job_id}:retry")
    async def retry_background_job(
        request: Request,
        job_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        job = await _background_job_repository(request).retry(
            owner_user_id=user.id,
            source_job_id=job_id,
            new_job_id=f"job_{uuid4().hex}",
        )
        if job is None:
            raise ApiErrorException("BUSINESS_CONFLICT")
        await _background_job_runtime(request).start()
        return success_response(request, _background_job_payload(job), status_code=202)

    @app.get("/feedback")
    async def list_feedback(
        request: Request,
        user: Annotated[UserRecord, Depends(current_user)],
        target_type: Annotated[str, Query(alias="targetType")],
        target_id: Annotated[str, Query(alias="targetId")],
    ) -> object:
        try:
            feedback = await _feedback_service(request).list_for_target(
                owner_user_id=user.id,
                target_type=target_type,
                target_id=target_id,
            )
        except FeedbackError as exc:
            raise ApiErrorException(exc.code, exc.message) from exc
        return success_response(
            request,
            {"items": [_user_feedback_payload(item) for item in feedback]},
        )

    @app.post("/feedback")
    async def upsert_feedback(
        request: Request,
        body: UpsertFeedbackRequest,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        try:
            feedback = await _feedback_service(request).upsert(
                owner_user_id=user.id,
                target_type=body.target_type,
                target_id=body.target_id,
                subject_id=body.subject_id,
                rating=body.rating,
                reason=body.reason,
                comment=body.comment,
                correction=body.correction,
            )
        except FeedbackError as exc:
            raise ApiErrorException(exc.code, exc.message) from exc
        return success_response(request, _user_feedback_payload(feedback))

    @app.delete("/feedback/{feedback_id}")
    async def delete_feedback(
        request: Request,
        feedback_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        try:
            deleted = await _feedback_service(request).delete(
                owner_user_id=user.id,
                feedback_id=feedback_id,
            )
        except FeedbackError as exc:
            raise ApiErrorException(exc.code, exc.message) from exc
        if not deleted:
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, {"deleted": True, "feedbackId": feedback_id})

    @app.get("/mcp/connections")
    async def list_mcp_connections(
        request: Request,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        records = await _mcp_connection_service(request).list(owner_user_id=user.id)
        return success_response(
            request,
            {"items": [_mcp_connection_payload(record) for record in records]},
        )

    @app.post("/mcp/connections")
    async def create_mcp_connection(
        request: Request,
        body: McpConnectionMutationRequest,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        try:
            record = await _mcp_connection_service(request).create(
                owner_user_id=user.id,
                **body.model_dump(),
            )
        except McpConnectionError as exc:
            raise ApiErrorException(exc.code, exc.message) from exc
        return success_response(request, _mcp_connection_payload(record), status_code=201)

    @app.put("/mcp/connections/{connection_id}")
    async def update_mcp_connection(
        request: Request,
        connection_id: str,
        body: McpConnectionMutationRequest,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        try:
            record = await _mcp_connection_service(request).update(
                owner_user_id=user.id,
                connection_id=connection_id,
                **body.model_dump(),
            )
        except McpConnectionError as exc:
            raise ApiErrorException(exc.code, exc.message) from exc
        return success_response(request, _mcp_connection_payload(record))

    @app.delete("/mcp/connections/{connection_id}")
    async def delete_mcp_connection(
        request: Request,
        connection_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        deleted = await _mcp_connection_service(request).delete(
            owner_user_id=user.id,
            connection_id=connection_id,
        )
        if not deleted:
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, {"deleted": True, "connectionId": connection_id})

    @app.post("/mcp/connections/{connection_id}:check")
    async def check_mcp_connection(
        request: Request,
        connection_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        try:
            record, tools = await _mcp_connection_service(request).check(
                owner_user_id=user.id,
                connection_id=connection_id,
            )
        except McpConnectionError as exc:
            raise ApiErrorException(exc.code, exc.message) from exc
        return success_response(
            request,
            {
                "connection": _mcp_connection_payload(record),
                "tools": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": tool.input_schema,
                        "serverName": tool.server_name,
                    }
                    for tool in tools
                ],
            },
        )

    @app.get("/knowledge-bases")
    async def list_knowledge_bases(
        request: Request,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        return success_response(
            request,
            {
                "items": [
                    {
                        "id": f"kb_{user.id}",
                        "name": "Personal knowledge base",
                        "ownerUserId": user.id,
                    }
                ]
            },
        )

    @app.get("/knowledge-bases/{knowledge_base_id}/documents")
    async def list_knowledge_documents(
        request: Request,
        knowledge_base_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        _ensure_knowledge_base_access(user, knowledge_base_id)
        documents = await _memory_repositories(request).documents.list_documents(
            owner_user_id=user.id,
            knowledge_base_id=knowledge_base_id,
        )
        return success_response(
            request,
            {"items": [_knowledge_document_payload(document) for document in documents]},
        )

    @app.post("/knowledge-bases/{knowledge_base_id}/documents")
    async def upload_knowledge_document(
        request: Request,
        knowledge_base_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
        file: Annotated[UploadFile, File()],
        overwrite: Annotated[bool, Form()] = False,
        chunking: Annotated[str, Form()] = "",
    ) -> object:
        _ensure_knowledge_base_access(user, knowledge_base_id)
        content = await file.read()
        try:
            _validate_upload(file, content)
            try:
                indexable_text = extract_indexable_text(file.filename or "document", content)
            except ValueError as exc:
                raise ApiErrorException("VALIDATION_INVALID_ARGUMENT", str(exc)) from exc
            chunking_configuration = _parse_chunking_configuration(chunking)
            content_hash = f"sha256:{sha256(content).hexdigest()}"
            repositories = _memory_repositories(request)
            duplicate = await repositories.documents.find_active_by_hash(
                owner_user_id=user.id,
                knowledge_base_id=knowledge_base_id,
                content_hash=content_hash,
            )
            if duplicate is not None and not overwrite:
                raise ApiErrorException("BUSINESS_CONFLICT")
            if duplicate is not None:
                _delete_document_vectors(
                    request,
                    tenant_id=user.id,
                    knowledge_base_id=knowledge_base_id,
                    document_id=duplicate.id,
                )
                await repositories.documents.mark_document_deleted(
                    owner_user_id=user.id,
                    knowledge_base_id=knowledge_base_id,
                    document_id=duplicate.id,
                )
            document = await repositories.documents.create_document(
                owner_user_id=user.id,
                document_id=f"doc_{uuid4().hex}",
                knowledge_base_id=knowledge_base_id,
                filename=file.filename or "document",
                size_bytes=len(content),
                mime_type=file.content_type or "application/octet-stream",
                content_hash=content_hash,
                metadata={
                    "upload": "user-selected",
                    "indexableText": indexable_text,
                    "chunking": chunking_configuration,
                },
            )
        finally:
            await file.close()
        return success_response(
            request,
            {
                "document": _knowledge_document_payload(document),
                "duplicateOfDocumentId": duplicate.id if duplicate is not None else None,
                "overwrite": overwrite,
            },
            status_code=201,
        )

    @app.get("/knowledge-bases/{knowledge_base_id}/documents/{document_id}")
    async def get_knowledge_document(
        request: Request,
        knowledge_base_id: str,
        document_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        _ensure_knowledge_base_access(user, knowledge_base_id)
        document = await _memory_repositories(request).documents.get_document(
            owner_user_id=user.id,
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
        )
        if document is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, _knowledge_document_payload(document))

    @app.get("/knowledge-bases/{knowledge_base_id}/documents/{document_id}/chunk-preview")
    async def get_document_chunk_preview(
        request: Request,
        knowledge_base_id: str,
        document_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        _ensure_knowledge_base_access(user, knowledge_base_id)
        document = await _memory_repositories(request).documents.get_document(
            owner_user_id=user.id, knowledge_base_id=knowledge_base_id, document_id=document_id
        )
        if document is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        configuration = _document_chunking_payload(document)
        chunks = chunk_document_text(
            _decode_indexable_document(document),
            strategy=cast(str, configuration["strategy"]),
            chunk_size=_runtime_chunk_size(configuration),
            chunk_overlap=_runtime_chunk_overlap(configuration),
        )
        return success_response(
            request,
            {
                "preview": {
                    "configuration": configuration,
                    "totalChunks": len(chunks),
                    "truncated": len(chunks) > 12,
                    "items": [
                        {
                            "index": item.index,
                            "characterCount": len(item.content),
                            "excerpt": item.content[:400],
                            **({"headingPath": item.heading_path} if item.heading_path else {}),
                        }
                        for item in chunks[:12]
                    ],
                }
            },
        )

    @app.delete("/knowledge-bases/{knowledge_base_id}/documents/{document_id}")
    async def delete_knowledge_document(
        request: Request,
        knowledge_base_id: str,
        document_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        _ensure_knowledge_base_access(user, knowledge_base_id)
        repositories = _memory_repositories(request)
        document = await repositories.documents.get_document(
            owner_user_id=user.id,
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
        )
        if document is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        _delete_document_vectors(
            request,
            tenant_id=user.id,
            knowledge_base_id=knowledge_base_id,
            document_id=document.id,
        )
        deleted = await repositories.documents.mark_document_deleted(
            owner_user_id=user.id,
            knowledge_base_id=knowledge_base_id,
            document_id=document.id,
        )
        if deleted is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, {"deleted": True, "documentId": document.id})

    @app.post("/knowledge-bases/{knowledge_base_id}/documents/{document_id}/index-tasks")
    async def create_document_index_task(
        request: Request,
        knowledge_base_id: str,
        document_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        _ensure_knowledge_base_access(user, knowledge_base_id)
        document = await _memory_repositories(request).documents.get_document(
            owner_user_id=user.id,
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
        )
        if document is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        task = await _memory_repositories(request).document_index_tasks.create_task(
            owner_user_id=user.id,
            task_id=f"index_task_{uuid4().hex}",
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
            status="pending",
        )
        await _schedule_index_task(request, owner_user_id=user.id, task_id=task.id)
        return success_response(
            request,
            {"task": _document_index_task_payload(task), "scheduled": True},
            status_code=202,
        )

    @app.get("/knowledge-bases/{knowledge_base_id}/documents/{document_id}/index-tasks/{task_id}")
    async def get_document_index_task(
        request: Request,
        knowledge_base_id: str,
        document_id: str,
        task_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        _ensure_knowledge_base_access(user, knowledge_base_id)
        task = await _memory_repositories(request).document_index_tasks.get_task(
            owner_user_id=user.id,
            task_id=task_id,
        )
        if (
            task is None
            or task.knowledge_base_id != knowledge_base_id
            or task.document_id != document_id
        ):
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, _document_index_task_payload(task))

    @app.post(
        "/knowledge-bases/{knowledge_base_id}/documents/{document_id}/index-tasks/{task_id}:retry"
    )
    async def retry_document_index_task(
        request: Request,
        knowledge_base_id: str,
        document_id: str,
        task_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        _ensure_knowledge_base_access(user, knowledge_base_id)
        previous = await _memory_repositories(request).document_index_tasks.get_task(
            owner_user_id=user.id,
            task_id=task_id,
        )
        if (
            previous is None
            or previous.knowledge_base_id != knowledge_base_id
            or previous.document_id != document_id
        ):
            raise ApiErrorException("AUTH_FORBIDDEN")
        if previous.status != "failed":
            raise ApiErrorException("BUSINESS_CONFLICT")
        task = await _memory_repositories(request).document_index_tasks.create_retry(
            owner_user_id=user.id,
            task_id=f"index_task_{uuid4().hex}",
            retry_of_task_id=previous.id,
        )
        await _schedule_index_task(request, owner_user_id=user.id, task_id=task.id)
        return success_response(
            request,
            {
                "task": _document_index_task_payload(task),
                "retriedFromTaskId": previous.id,
                "scheduled": True,
            },
            status_code=202,
        )

    @app.post("/chat/sessions")
    async def create_chat_session(
        request: Request,
        body: CreateChatSessionRequest,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        title = _normalize_chat_title(body.title)
        repositories = _memory_repositories(request)
        session = await repositories.chat.create_session(
            owner_user_id=user.id,
            session_id=f"chat_{uuid4().hex}",
            title=title,
        )
        return success_response(
            request,
            _chat_session_payload(session, _context_window_tokens(request)),
            status_code=201,
        )

    @app.get("/chat/configuration")
    async def get_chat_configuration(
        request: Request, user: Annotated[UserRecord, Depends(current_user)]
    ) -> object:
        prompts, skills, record = await _read_chat_configuration(request, owner_user_id=user.id)
        return success_response(request, _chat_configuration_payload(prompts, skills, record))

    @app.put("/chat/configuration")
    async def update_chat_configuration(
        request: Request,
        body: UpdateChatAssemblyConfigurationRequest,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        prompt_repository = _chat_prompt_repository(request)
        skill_repository = _chat_skill_repository(request)
        configuration_repository = _chat_configuration_repository(request)
        prompt = await prompt_repository.get(
            owner_user_id=user.id,
            prompt_id=body.system_prompt_id,
        )
        if prompt is None:
            raise ApiErrorException("VALIDATION_INVALID_ARGUMENT")
        skill_ids = list(dict.fromkeys(body.skill_ids))
        for skill_id in skill_ids:
            skill = await skill_repository.get(owner_user_id=user.id, skill_id=skill_id)
            if skill is None:
                raise ApiErrorException("VALIDATION_INVALID_ARGUMENT")
        await configuration_repository.update(
            owner_user_id=user.id,
            system_prompt_id=prompt.id,
            skill_ids=skill_ids,
        )
        prompts, skills, record = await _read_chat_configuration(request, owner_user_id=user.id)
        return success_response(request, _chat_configuration_payload(prompts, skills, record))

    @app.post("/chat/prompts")
    async def create_chat_prompt(
        request: Request,
        body: CreateChatPromptRequest,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        try:
            label, content = validate_chat_prompt_content(body.label, body.content)
        except ValueError as exc:
            raise ApiErrorException("VALIDATION_INVALID_ARGUMENT", str(exc)) from exc
        prompt = await _chat_prompt_repository(request).create(
            owner_user_id=user.id,
            prompt_id=f"prompt_{uuid4().hex}",
            label=label,
            content=content,
        )
        return success_response(request, _chat_prompt_payload(prompt), status_code=201)

    @app.put("/chat/prompts/{prompt_id}")
    async def update_chat_prompt(
        request: Request,
        prompt_id: str,
        body: UpdateChatPromptRequest,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        try:
            label, content = validate_chat_prompt_content(body.label, body.content)
        except ValueError as exc:
            raise ApiErrorException("VALIDATION_INVALID_ARGUMENT", str(exc)) from exc
        prompt = await _chat_prompt_repository(request).update(
            owner_user_id=user.id,
            prompt_id=prompt_id,
            label=label,
            content=content,
        )
        if prompt is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, _chat_prompt_payload(prompt))

    @app.delete("/chat/prompts/{prompt_id}")
    async def delete_chat_prompt(
        request: Request,
        prompt_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        prompt_repository = _chat_prompt_repository(request)
        configuration_repository = _chat_configuration_repository(request)
        target = await prompt_repository.get(owner_user_id=user.id, prompt_id=prompt_id)
        if target is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        deleted = await prompt_repository.delete(owner_user_id=user.id, prompt_id=prompt_id)
        default_prompt = await prompt_repository.ensure_default(
            owner_user_id=user.id,
            label=DEFAULT_CHAT_PROMPT_LABEL,
            content=DEFAULT_CHAT_PROMPT_CONTENT,
        )
        configuration = await configuration_repository.get_or_create(
            owner_user_id=user.id,
            system_prompt_id=default_prompt.id,
            skill_ids=[],
        )
        if configuration.system_prompt_id == prompt_id:
            await configuration_repository.update(
                owner_user_id=user.id,
                system_prompt_id=default_prompt.id,
                skill_ids=configuration.skill_ids,
            )
        return success_response(request, {"promptId": prompt_id, "deleted": deleted})

    @app.post("/chat/skills")
    async def upload_chat_skill(
        request: Request,
        file: Annotated[UploadFile, File()],
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        content = await file.read()
        try:
            validated = validate_skill_upload(file.filename, content)
            skill = await _chat_skill_repository(request).create(
                owner_user_id=user.id,
                skill_id=f"skill_{uuid4().hex}",
                filename=validated.filename,
                name=validated.name,
                description=validated.description,
                content=validated.content,
                size_bytes=len(content),
            )
        except ValueError as exc:
            raise ApiErrorException("VALIDATION_INVALID_ARGUMENT", str(exc)) from exc
        return success_response(request, _chat_skill_payload(skill), status_code=201)

    @app.delete("/chat/skills/{skill_id}")
    async def delete_chat_skill(
        request: Request,
        skill_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        deleted = await _chat_skill_repository(request).delete(
            owner_user_id=user.id,
            skill_id=skill_id,
        )
        if not deleted:
            raise ApiErrorException("AUTH_FORBIDDEN")
        configuration_repository = _chat_configuration_repository(request)
        default_prompt = await _chat_prompt_repository(request).ensure_default(
            owner_user_id=user.id,
            label=DEFAULT_CHAT_PROMPT_LABEL,
            content=DEFAULT_CHAT_PROMPT_CONTENT,
        )
        configuration = await configuration_repository.get_or_create(
            owner_user_id=user.id,
            system_prompt_id=default_prompt.id,
            skill_ids=[],
        )
        skill_ids = [item for item in configuration.skill_ids if item != skill_id]
        if skill_ids != configuration.skill_ids:
            await configuration_repository.update(
                owner_user_id=user.id,
                system_prompt_id=configuration.system_prompt_id,
                skill_ids=skill_ids,
            )
        return success_response(request, {"skillId": skill_id, "deleted": True})

    @app.get("/chat/sessions")
    async def list_chat_sessions(
        request: Request,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        sessions = await _memory_repositories(request).chat.list_sessions(owner_user_id=user.id)
        return success_response(
            request,
            {
                "items": [
                    _chat_session_payload(session, _context_window_tokens(request))
                    for session in sessions
                ]
            },
        )

    @app.get("/chat/sessions/{session_id}")
    async def get_chat_session(
        request: Request,
        session_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        repositories = _memory_repositories(request)
        session = await repositories.chat.get_session(
            owner_user_id=user.id,
            session_id=session_id,
        )
        if session is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        messages = await repositories.chat.list_messages(
            owner_user_id=user.id,
            session_id=session.id,
        )
        return success_response(
            request,
            {
                "session": _chat_session_payload(session, _context_window_tokens(request)),
                "messages": [_chat_message_payload(message) for message in messages],
            },
        )

    @app.get("/chat/sessions/{session_id}/tool-call-audits")
    async def list_chat_tool_call_audits(
        request: Request,
        session_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        repositories = _memory_repositories(request)
        session = await repositories.chat.get_session(
            owner_user_id=user.id,
            session_id=session_id,
        )
        if session is None or repositories.tool_call_audits is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        audits = await repositories.tool_call_audits.list_for_chat_session(
            owner_user_id=user.id,
            chat_session_id=session.id,
        )
        return success_response(
            request,
            {"items": [_agent_tool_call_audit_payload(audit) for audit in audits]},
        )

    @app.put("/chat/sessions/{session_id}/memory")
    async def update_chat_memory(
        request: Request,
        session_id: str,
        body: UpdateChatMemoryRequest,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        if body.mode not in SUPPORTED_CHAT_MEMORY_MODES:
            raise ApiErrorException("VALIDATION_INVALID_ARGUMENT")
        repositories = _memory_repositories(request)
        session = await repositories.chat.get_session(owner_user_id=user.id, session_id=session_id)
        if session is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        history = await repositories.chat.list_messages(
            owner_user_id=user.id, session_id=session_id
        )
        service, prompt = await _chat_memory_context(request, owner_user_id=user.id)
        updated = await service.set_mode(
            owner_user_id=user.id,
            session=session,
            mode=body.mode,
            history=history,
            system_prompt=prompt,
        )
        return success_response(
            request, _chat_session_payload(updated, service.context_window_tokens)
        )

    @app.post("/chat/sessions/{session_id}/memory:compact")
    async def compact_chat_memory(
        request: Request,
        session_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        repositories = _memory_repositories(request)
        session = await repositories.chat.get_session(owner_user_id=user.id, session_id=session_id)
        if session is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        history = await repositories.chat.list_messages(
            owner_user_id=user.id, session_id=session_id
        )
        service, prompt = await _chat_memory_context(request, owner_user_id=user.id)
        updated = await service.compact(
            owner_user_id=user.id,
            session=session,
            history=history,
            system_prompt=prompt,
        )
        return success_response(
            request, _chat_session_payload(updated, service.context_window_tokens)
        )

    @app.post("/chat/sessions/{session_id}/messages")
    async def append_chat_message(
        request: Request,
        session_id: str,
        body: AppendChatMessageRequest,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        repositories = _memory_repositories(request)
        session = await repositories.chat.get_session(
            owner_user_id=user.id,
            session_id=session_id,
        )
        if session is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        if body.role == "user":
            history = await repositories.chat.list_messages(
                owner_user_id=user.id, session_id=session.id
            )
            service, prompt = await _chat_memory_context(request, owner_user_id=user.id)
            try:
                await service.prepare_message(
                    owner_user_id=user.id,
                    session=session,
                    history=history,
                    system_prompt=prompt,
                    content=body.content,
                )
            except ChatContextLimitReached as exc:
                raise ApiErrorException("CHAT_CONTEXT_LIMIT_REACHED") from exc
        message = await repositories.chat.append_message(
            owner_user_id=user.id,
            message_id=f"message_{uuid4().hex}",
            session_id=session.id,
            role=body.role,
            content=body.content,
            metadata=body.metadata,
        )
        updated_session = await _maybe_generate_chat_title(
            repositories,
            user_id=user.id,
            session=session,
            message_role=body.role,
            message_content=body.content,
        )
        return success_response(
            request,
            {
                "session": _chat_session_payload(updated_session, _context_window_tokens(request)),
                "message": _chat_message_payload(message),
            },
            status_code=201,
        )

    @app.post("/chat/sessions/{session_id}/messages:stream")
    async def stream_chat_message(
        request: Request,
        session_id: str,
        body: StreamChatMessageRequest,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> StreamingResponse:
        repositories = _memory_repositories(request)
        session = await repositories.chat.get_session(
            owner_user_id=user.id,
            session_id=session_id,
        )
        if session is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        service = ChatStreamingService(
            repositories=repositories,
            agent_runner=_chat_agent_runner(request),
            memory_service=_chat_memory_service(request),
        )

        async def event_stream() -> AsyncIterator[str]:
            async for event in service.stream_message(
                owner_user_id=user.id,
                session=session,
                content=body.content,
                metadata=body.metadata,
                accessible_knowledge_base_ids=_accessible_knowledge_base_ids(user),
            ):
                yield encode_sse(event)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @app.post("/chat/sessions/{session_id}/messages:clear")
    async def clear_chat_messages(
        request: Request,
        session_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        repositories = _memory_repositories(request)
        session = await repositories.chat.get_session(
            owner_user_id=user.id,
            session_id=session_id,
        )
        if session is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        deleted_messages = await repositories.chat.clear_messages(
            owner_user_id=user.id,
            session_id=session.id,
        )
        return success_response(
            request,
            {
                "sessionId": session.id,
                "cleared": True,
                "deletedMessages": deleted_messages,
            },
        )

    @app.delete("/chat/sessions/{session_id}")
    async def delete_chat_session(
        request: Request,
        session_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        deleted = await _memory_repositories(request).chat.delete_session(
            owner_user_id=user.id,
            session_id=session_id,
        )
        if not deleted:
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, {"sessionId": session_id, "deleted": True})

    @app.post("/aiops/diagnostics")
    async def create_aiops_diagnostic(
        request: Request,
        body: CreateAiopsDiagnosticRequest,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        task = await _memory_repositories(request).diagnostics.create_task(
            owner_user_id=user.id,
            task_id=f"diagnostic_{uuid4().hex}",
            status="accepted",
            query=body.query,
            input_payload={"query": body.query, "alert": body.alert},
            result_payload={},
        )
        job = await _background_job_repository(request).enqueue(
            owner_user_id=user.id,
            job_id=f"job_{uuid4().hex}",
            kind="aiops_diagnosis",
            resource_type="aiops_diagnostic",
            resource_id=task.id,
            payload={"diagnosticId": task.id},
            max_attempts=1,
            timeout_seconds=1800,
        )
        await _background_job_runtime(request).start()
        payload = _diagnostic_task_payload(task)
        payload["backgroundJob"] = _background_job_payload(job)
        return success_response(
            request,
            payload,
            status_code=202,
        )

    @app.post("/aiops/alert-events")
    async def ingest_aiops_alert_event(
        request: Request,
        body: AlertEvent,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        service = AlertGatewayService(
            repositories=_memory_repositories(request),
            publisher=_alert_event_publisher(request),
            settings=_event_ingestion_settings(request),
        )
        try:
            accepted = await service.accept(owner_user_id=user.id, event=body)
        except BrokerUnavailableError as exc:
            emit_event(
                logger,
                "event.publish.failed",
                eventId=body.event_id,
                incidentId=body.incident_id,
                errorCategory=exc.__class__.__name__,
            )
            raise ApiErrorException(
                "SYSTEM_UNAVAILABLE",
                "The alert event broker is temporarily unavailable.",
            ) from exc
        emit_event(
            logger,
            "event.publish.completed",
            eventId=accepted.event_id,
            incidentId=accepted.incident_id,
            diagnosticTaskId=accepted.task.id,
            topic=accepted.receipt.topic,
            partition=accepted.receipt.partition,
            offset=accepted.receipt.offset,
        )
        return success_response(
            request,
            {
                "accepted": True,
                "eventId": accepted.event_id,
                "incidentId": accepted.incident_id,
                "diagnostic": _diagnostic_task_payload(accepted.task),
                "broker": {
                    "topic": accepted.receipt.topic,
                    "partition": accepted.receipt.partition,
                    "offset": accepted.receipt.offset,
                },
            },
            status_code=202,
        )

    @app.post("/aiops/diagnostics/{diagnostic_id}/remediation-approvals")
    async def create_remediation_approval(
        request: Request,
        diagnostic_id: str,
        body: CreateRemediationApprovalRequest,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        task = await _memory_repositories(request).diagnostics.get_task(
            owner_user_id=user.id,
            task_id=diagnostic_id,
        )
        if task is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        approval = await _remediation_approval_repository(request).create(
            owner_user_id=user.id,
            approval_id=f"remediation_{uuid4().hex}",
            task_id=task.id,
            tool_name=body.tool_name,
            arguments=body.arguments,
            rationale=body.rationale,
            risk_level=body.risk_level,
        )
        return success_response(
            request,
            _remediation_approval_payload(approval),
            status_code=201,
        )

    @app.get("/aiops/diagnostics/{diagnostic_id}/remediation-approvals")
    async def list_remediation_approvals(
        request: Request,
        diagnostic_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        task = await _memory_repositories(request).diagnostics.get_task(
            owner_user_id=user.id,
            task_id=diagnostic_id,
        )
        if task is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        approvals = await _remediation_approval_repository(request).list_for_task(
            owner_user_id=user.id,
            task_id=task.id,
        )
        return success_response(
            request,
            {"items": [_remediation_approval_payload(item) for item in approvals]},
        )

    @app.post("/aiops/remediation-approvals/{approval_id}:decide")
    async def decide_remediation_approval(
        request: Request,
        approval_id: str,
        body: DecideRemediationApprovalRequest,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        service = RemediationApprovalService(
            repository=_remediation_approval_repository(request),
            publisher=_alert_event_publisher(request),
            settings=_event_ingestion_settings(request),
        )
        try:
            approval = await service.decide(
                owner_user_id=user.id,
                approval_id=approval_id,
                decision=body.decision,
                decision_note=body.decision_note,
            )
        except RemediationDecisionError as exc:
            existing = await _remediation_approval_repository(request).get(
                owner_user_id=user.id,
                approval_id=approval_id,
            )
            code = "AUTH_FORBIDDEN" if existing is None else "BUSINESS_CONFLICT"
            raise ApiErrorException(code) from exc
        except BrokerUnavailableError as exc:
            raise ApiErrorException(
                "SYSTEM_UNAVAILABLE",
                "The remediation command broker is temporarily unavailable.",
            ) from exc
        return success_response(request, _remediation_approval_payload(approval))

    @app.get("/aiops/alerts/active")
    async def list_active_alerts(
        request: Request,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        del user
        try:
            alerts = await _active_alert_provider(request).list_active_alerts()
        except AlertProviderError as exc:
            emit_event(logger, "alerts.fetch.failed")
            raise ApiErrorException(
                "SYSTEM_UNAVAILABLE",
                "Unable to retrieve active alerts from the configured alert provider.",
            ) from exc
        return success_response(
            request,
            {"items": [_active_alert_payload(alert) for alert in alerts]},
        )

    @app.get("/aiops/diagnostics")
    async def list_aiops_diagnostics(
        request: Request,
        user: Annotated[UserRecord, Depends(current_user)],
        start_at: Annotated[datetime | None, Query(alias="startAt")] = None,
        end_at: Annotated[datetime | None, Query(alias="endAt")] = None,
    ) -> object:
        tasks = await _memory_repositories(request).diagnostics.list_tasks(
            owner_user_id=user.id,
            time_range=TimeRangeFilter(start_at=start_at, end_at=end_at),
        )
        return success_response(
            request,
            {"items": [_diagnostic_task_payload(task) for task in reversed(tasks)]},
        )

    @app.get("/aiops/diagnostic-cases")
    async def list_aiops_diagnostic_cases(
        request: Request,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        cases = await _memory_repositories(request).diagnostics.list_cases(owner_user_id=user.id)
        return success_response(
            request,
            {"items": [_diagnostic_case_payload(case) for case in cases]},
        )

    @app.get("/aiops/diagnostic-cases/{case_id}")
    async def get_aiops_diagnostic_case(
        request: Request,
        case_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        case = await _memory_repositories(request).diagnostics.get_case(
            owner_user_id=user.id,
            case_id=case_id,
        )
        if case is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        return success_response(request, _diagnostic_case_payload(case))

    @app.get("/aiops/diagnostics/{diagnostic_id}")
    async def get_aiops_diagnostic(
        request: Request,
        diagnostic_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        task = await _memory_repositories(request).diagnostics.get_task(
            owner_user_id=user.id,
            task_id=diagnostic_id,
        )
        if task is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        reports = await _memory_repositories(request).diagnostics.list_reports(
            owner_user_id=user.id,
            task_id=task.id,
        )
        return success_response(request, _diagnostic_task_payload(task, reports=reports))

    @app.get("/aiops/diagnostics/{diagnostic_id}/evidence-chain")
    async def get_aiops_evidence_chain(
        request: Request,
        diagnostic_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        repositories = _memory_repositories(request)
        task = await repositories.diagnostics.get_task(
            owner_user_id=user.id,
            task_id=diagnostic_id,
        )
        if task is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        steps, evidence, report_links, reports, checkpoints = await asyncio.gather(
            repositories.diagnostics.list_steps(owner_user_id=user.id, task_id=task.id),
            repositories.diagnostics.list_evidence(owner_user_id=user.id, task_id=task.id),
            repositories.diagnostics.list_report_evidence_links(
                owner_user_id=user.id,
                task_id=task.id,
            ),
            repositories.diagnostics.list_reports(owner_user_id=user.id, task_id=task.id),
            repositories.diagnostics.list_checkpoints(owner_user_id=user.id, task_id=task.id),
        )
        tool_audits = []
        if repositories.tool_call_audits is not None:
            tool_audits = await repositories.tool_call_audits.list_for_diagnostic_task(
                owner_user_id=user.id,
                diagnostic_task_id=task.id,
            )
        report_evidence_ids = _report_evidence_ids(report_links)
        return success_response(
            request,
            {
                "task": _diagnostic_task_payload(task, reports=reports),
                "steps": [_diagnostic_step_payload(step) for step in steps],
                "toolCalls": [_agent_tool_call_audit_payload(audit) for audit in tool_audits],
                "evidence": [_diagnostic_evidence_payload(item) for item in evidence],
                "reports": [
                    _diagnostic_report_payload(
                        report,
                        evidence_ids=report_evidence_ids.get(report.id, []),
                    )
                    for report in reports
                ],
                "reportEvidenceLinks": [
                    _report_evidence_link_payload(link) for link in report_links
                ],
                "checkpoints": [
                    _graph_checkpoint_payload(checkpoint) for checkpoint in checkpoints
                ],
            },
        )

    @app.post("/aiops/diagnostics/{diagnostic_id}:stream")
    async def stream_aiops_diagnostic(
        request: Request,
        diagnostic_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> StreamingResponse:
        task = await _memory_repositories(request).diagnostics.get_task(
            owner_user_id=user.id,
            task_id=diagnostic_id,
        )
        if task is None:
            raise ApiErrorException("AUTH_FORBIDDEN")
        repository = _background_job_repository(request)
        job = await repository.find_for_resource(
            owner_user_id=user.id,
            resource_type="aiops_diagnostic",
            resource_id=task.id,
        )
        if job is None:
            raise ApiErrorException("BUSINESS_NOT_FOUND")
        await _background_job_runtime(request).start()

        async def event_stream() -> AsyncIterator[str]:
            sequence = 0
            error_emitted = False
            while True:
                events = await repository.list_events(
                    owner_user_id=user.id,
                    job_id=job.id,
                    after_sequence=sequence,
                )
                for stored in events:
                    sequence = stored.sequence
                    error_emitted = error_emitted or stored.payload.get("type") == "error"
                    yield encode_sse(stored.payload)
                current = await repository.get(owner_user_id=user.id, job_id=job.id)
                if current is None:
                    return
                if current.status in {"succeeded", "failed", "cancelled"} and not events:
                    if current.status == "failed" and not error_emitted:
                        yield encode_sse(_background_job_error_event())
                    return
                await asyncio.sleep(0.1)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    @app.post("/aiops/diagnostics/{diagnostic_id}:save-to-knowledge")
    async def save_aiops_diagnostic_case(
        request: Request,
        diagnostic_id: str,
        user: Annotated[UserRecord, Depends(current_user)],
    ) -> object:
        repositories = _memory_repositories(request)
        task = await repositories.diagnostics.get_task(owner_user_id=user.id, task_id=diagnostic_id)
        if task is None or task.status != "succeeded":
            raise ApiErrorException("AUTH_FORBIDDEN")
        reports = await repositories.diagnostics.list_reports(
            owner_user_id=user.id,
            task_id=task.id,
        )
        report = reports[-1] if reports else None
        if report is None:
            raise ApiErrorException("BUSINESS_NOT_FOUND")
        evidence = await repositories.diagnostics.list_evidence(
            owner_user_id=user.id,
            task_id=task.id,
        )
        content = _diagnostic_case_content(task, report, evidence)
        content_hash = f"sha256:{sha256(content.encode()).hexdigest()}"
        knowledge_base_id = f"kb_{user.id}"
        duplicate = await repositories.documents.find_active_by_hash(
            owner_user_id=user.id,
            knowledge_base_id=knowledge_base_id,
            content_hash=content_hash,
        )
        if duplicate is not None:
            raise ApiErrorException("BUSINESS_CONFLICT")
        document = await repositories.documents.create_document(
            owner_user_id=user.id,
            document_id=f"doc_{uuid4().hex}",
            knowledge_base_id=knowledge_base_id,
            filename=f"diagnostic-case-{task.id[-12:]}.md",
            size_bytes=len(content.encode()),
            mime_type="text/markdown",
            content_hash=content_hash,
            source="aiops-diagnostic",
            metadata={
                "indexableText": content,
                "diagnosticTaskId": task.id,
                "diagnosticReportId": report.id,
                "evidenceIds": [item.id for item in evidence],
            },
        )
        index_task = await repositories.document_index_tasks.create_task(
            owner_user_id=user.id,
            task_id=f"index_task_{uuid4().hex}",
            knowledge_base_id=knowledge_base_id,
            document_id=document.id,
        )
        await _schedule_index_task(request, owner_user_id=user.id, task_id=index_task.id)
        return success_response(
            request,
            {
                "document": _knowledge_document_payload(document),
                "task": _document_index_task_payload(index_task),
                "scheduled": True,
            },
            status_code=202,
        )

    return app


def _memory_repositories(request: Request) -> MemoryRepositories:
    return request.app.state.memory_repositories


def _background_job_repository(request: Request) -> BackgroundJobRepository:
    return _background_job_repository_from_app(request.app)


def _background_job_repository_from_app(app: FastAPI) -> BackgroundJobRepository:
    repository = cast(MemoryRepositories, app.state.memory_repositories).background_jobs
    if repository is None:
        raise RuntimeError("Background job repository is unavailable.")
    return repository


def _background_job_runtime(request: Request) -> BackgroundJobRuntime:
    return _background_job_runtime_from_app(request.app)


def _background_job_runtime_from_app(app: FastAPI) -> BackgroundJobRuntime:
    return cast(BackgroundJobRuntime, app.state.background_job_runtime)


def _remediation_approval_repository(request: Request) -> RemediationApprovalRepository:
    repository = _memory_repositories(request).remediation_approvals
    if repository is None:
        raise RuntimeError("Remediation approval repository is unavailable.")
    return repository


def _feedback_service(request: Request) -> UserFeedbackService:
    return UserFeedbackService(_memory_repositories(request))


def _mcp_connection_service(request: Request) -> McpConnectionService:
    config = project_config_section("mcp", config_path=request.app.state.project_config_path)
    return McpConnectionService(
        _memory_repositories(request),
        default_url=required_str(config, "clsSseUrl"),
        default_timeout_seconds=required_int(config, "timeoutSeconds"),
        default_retries=required_int(config, "retries"),
    )


async def _schedule_index_task(request: Request, *, owner_user_id: str, task_id: str) -> None:
    result = _index_task_scheduler(request).schedule(
        owner_user_id=owner_user_id,
        task_id=task_id,
    )
    if inspect.isawaitable(result):
        await result


def _document_index_job_handler(
    app: FastAPI,
) -> Callable[[BackgroundJobContext], Awaitable[None]]:
    async def handle(context: BackgroundJobContext) -> None:
        await context.raise_if_cancelled()
        result = await _document_indexing_service_from_app(app).run_task(
            owner_user_id=context.job.owner_user_id,
            task_id=context.job.resource_id,
        )
        if result.status != "succeeded":
            raise RuntimeError(result.failure_reason or "Document indexing failed.")

    return handle


def _aiops_job_handler(
    app: FastAPI,
) -> Callable[[BackgroundJobContext], Awaitable[None]]:
    async def handle(context: BackgroundJobContext) -> None:
        repositories = cast(MemoryRepositories, app.state.memory_repositories)
        task = await repositories.diagnostics.get_task(
            owner_user_id=context.job.owner_user_id,
            task_id=context.job.resource_id,
        )
        if task is None:
            raise RuntimeError("Diagnostic task is unavailable.")
        runner = _aiops_diagnostic_runner(_request_for_app(app))
        try:
            async for event in runner.stream(
                task=task,
                accessible_knowledge_base_ids=(f"kb_{context.job.owner_user_id}",),
            ):
                await context.raise_if_cancelled()
                await context.append_event(event)
        except JobCancelled:
            await repositories.diagnostics.update_task(
                owner_user_id=task.owner_user_id,
                task_id=task.id,
                status="cancelled",
                completed_at=datetime.now(timezone.utc),
            )
            raise
        updated = await repositories.diagnostics.get_task(
            owner_user_id=task.owner_user_id,
            task_id=task.id,
        )
        if updated is None or updated.status == "failed":
            raise RuntimeError("Diagnostic execution failed.")

    return handle


def _remediation_job_handler(
    app: FastAPI,
) -> Callable[[BackgroundJobContext], Awaitable[None]]:
    async def handle(context: BackgroundJobContext) -> None:
        await context.raise_if_cancelled()
        request = _request_for_app(app)
        service = RemediationApprovalService(
            repository=_remediation_approval_repository(request),
            publisher=_alert_event_publisher(request),
            settings=_event_ingestion_settings(request),
        )
        await service.dispatch_approved(
            owner_user_id=context.job.owner_user_id,
            approval_id=context.job.resource_id,
            require_completion=True,
        )

    return handle


def _request_for_app(app: FastAPI) -> Request:
    return Request(
        {
            "type": "http",
            "app": app,
            "headers": [],
            "method": "GET",
            "path": "/_background",
            "query_string": b"",
            "scheme": "http",
            "server": ("127.0.0.1", 8000),
            "client": ("127.0.0.1", 0),
            "root_path": "",
        }
    )


async def _cancel_background_resource(request: Request, job: BackgroundJobRecord) -> None:
    repositories = _memory_repositories(request)
    if job.resource_type == "document_index_task":
        await repositories.document_index_tasks.mark_cancelled(
            owner_user_id=job.owner_user_id,
            task_id=job.resource_id,
        )
    if job.resource_type == "aiops_diagnostic":
        await repositories.diagnostics.update_task(
            owner_user_id=job.owner_user_id,
            task_id=job.resource_id,
            status="cancelled",
            completed_at=datetime.now(timezone.utc),
        )


def _background_job_payload(job: BackgroundJobRecord) -> dict[str, object]:
    return {
        "id": job.id,
        "ownerUserId": job.owner_user_id,
        "kind": job.kind,
        "resourceType": job.resource_type,
        "resourceId": job.resource_id,
        "status": job.status,
        "attempt": job.attempt,
        "maxAttempts": job.max_attempts,
        "timeoutSeconds": job.timeout_seconds,
        "availableAt": job.available_at.isoformat(),
        "cancelRequestedAt": (
            job.cancel_requested_at.isoformat() if job.cancel_requested_at else None
        ),
        "retryOfJobId": job.retry_of_job_id,
        "errorMessage": job.error_message,
        "createdAt": job.created_at.isoformat(),
        "updatedAt": job.updated_at.isoformat(),
        "startedAt": job.started_at.isoformat() if job.started_at else None,
        "completedAt": job.completed_at.isoformat() if job.completed_at else None,
    }


def _background_job_error_event() -> dict[str, object]:
    category, http_status, message = ERROR_DEFINITIONS["SYSTEM_INTERNAL_ERROR"]
    return {
        "id": f"evt_{uuid4().hex}",
        "type": "error",
        "channel": "aiops",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error": {
            "code": "SYSTEM_INTERNAL_ERROR",
            "category": category,
            "httpStatus": http_status,
            "message": message,
        },
    }


def _user_feedback_payload(record: UserFeedbackRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "ownerUserId": record.owner_user_id,
        "targetType": record.target_type,
        "targetId": record.target_id,
        "subjectId": record.subject_id,
        "rating": record.rating,
        "reason": record.reason,
        "comment": record.comment,
        "correction": record.correction,
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
    }


def _mcp_connection_payload(record: McpConnectionRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "ownerUserId": record.owner_user_id,
        "name": record.name,
        "transport": record.transport,
        "url": record.url,
        "enabled": record.enabled,
        "timeoutSeconds": record.timeout_seconds,
        "retries": record.retries,
        "lastCheck": (
            {
                "ok": record.last_check_ok,
                "toolCount": record.last_tool_count or 0,
                "tools": record.last_tools,
                "error": record.last_error,
                "checkedAt": (
                    record.last_checked_at.isoformat() if record.last_checked_at else None
                ),
            }
            if record.last_check_ok is not None
            else None
        ),
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
    }


def _memory_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return cast(async_sessionmaker[AsyncSession], request.app.state.memory_session_factory)


async def _runtime_dependency_payload(request: Request) -> dict[str, dict[str, object]]:
    sqlite_result, milvus_result, llm_result, mcp_result = await asyncio.gather(
        _sqlite_readiness_payload(request),
        _milvus_readiness_payload(request),
        _llm_readiness_payload(request),
        _mcp_readiness_payload(request),
    )
    return {
        "sqlite": sqlite_result,
        "milvus": milvus_result,
        "llm": llm_result,
        "mcp": mcp_result,
    }


async def _sqlite_readiness_payload(request: Request) -> dict[str, object]:
    started_at = monotonic()
    try:
        async with _memory_session_factory(request)() as session:
            await session.execute(sql_text("SELECT 1"))
    except Exception:
        return {
            "ok": False,
            "engine": "sqlite",
            "latencyMs": _elapsed_ms(started_at),
            "error": "SQLite is unavailable.",
        }
    return {
        "ok": True,
        "engine": "sqlite",
        "latencyMs": _elapsed_ms(started_at),
        "error": None,
    }


async def _milvus_readiness_payload(request: Request) -> dict[str, object]:
    try:
        result = await run_in_threadpool(_vector_store(request).health_check)
    except Exception:
        return {
            "ok": False,
            "uri": None,
            "collectionName": None,
            "latencyMs": 0.0,
            "error": "Milvus is unavailable.",
        }
    payload = _milvus_health_payload(result)
    payload["error"] = None if result.ok else "Milvus is unavailable."
    return payload


async def _llm_readiness_payload(request: Request) -> dict[str, object]:
    try:
        result = await _llm_provider(request).check_readiness()
    except Exception:
        return {
            "ok": False,
            "provider": None,
            "model": None,
            "baseUrl": None,
            "latencyMs": 0.0,
            "error": "LLM provider is unavailable.",
        }
    return {
        "ok": result.ok,
        "provider": result.provider,
        "model": result.model,
        "baseUrl": result.base_url,
        "latencyMs": result.latency_ms,
        "error": None if result.ok else "LLM provider is unavailable.",
    }


async def _mcp_readiness_payload(request: Request) -> dict[str, object]:
    try:
        result = await _mcp_client(request).readiness()
    except Exception:
        return {
            "ok": False,
            "endpoint": None,
            "toolCount": 0,
            "error": "MCP server is unavailable.",
        }
    is_ready = result.get("ok") is True
    endpoint = result.get("endpoint")
    tool_count = result.get("toolCount")
    return {
        "ok": is_ready,
        "endpoint": endpoint if isinstance(endpoint, str) else None,
        "toolCount": tool_count if isinstance(tool_count, int) else 0,
        "error": None if is_ready else "MCP server is unavailable.",
    }


def _configuration_check_payload(request: Request) -> dict[str, dict[str, object]]:
    config_path = request.app.state.project_config_path
    configuration: dict[str, dict[str, object]] = {}
    try:
        load_memory_database_settings(config_path=config_path)
    except Exception:
        configuration["sqlite"] = {
            "valid": False,
            "engine": "sqlite",
            "error": "SQLite configuration is invalid.",
        }
    else:
        configuration["sqlite"] = {"valid": True, "engine": "sqlite", "error": None}
    try:
        llm_config = load_llm_provider_config(config_path=config_path)
    except Exception:
        configuration["llm"] = {"valid": False, "error": "LLM configuration is invalid."}
    else:
        configuration["llm"] = {
            "valid": True,
            "provider": llm_config.provider,
            "model": llm_config.chat_model,
            "baseUrl": llm_config.base_url,
            "error": None,
        }
    try:
        vector_config = load_milvus_vector_store_settings(config_path=config_path)
    except Exception:
        configuration["milvus"] = {"valid": False, "error": "Milvus configuration is invalid."}
    else:
        configuration["milvus"] = {
            "valid": True,
            "uri": vector_config.uri,
            "collectionName": vector_config.collection_name,
            "error": None,
        }
    try:
        mcp_config = project_config_section("mcp", config_path=config_path)
        mcp_endpoint = required_str(mcp_config, "clsSseUrl")
        required_int(mcp_config, "timeoutSeconds")
        required_int(mcp_config, "retries")
    except Exception:
        configuration["mcp"] = {"valid": False, "error": "MCP configuration is invalid."}
    else:
        configuration["mcp"] = {"valid": True, "endpoint": mcp_endpoint, "error": None}
    try:
        event_config = load_event_ingestion_settings(config_path=config_path)
    except Exception:
        configuration["eventIngestion"] = {
            "valid": False,
            "error": "Event ingestion configuration is invalid.",
        }
    else:
        configuration["eventIngestion"] = {
            "valid": True,
            "alertsTopic": event_config.alerts_topic,
            "updatesTopic": event_config.updates_topic,
            "error": None,
        }
    return configuration


def _elapsed_ms(started_at: float) -> float:
    return round((monotonic() - started_at) * 1000, 3)


def _vector_store(request: Request) -> MilvusHealthCheckProvider:
    return cast(MilvusHealthCheckProvider, request.app.state.vector_store)


def _document_vector_store(request: Request) -> DocumentVectorStoreProvider:
    return cast(DocumentVectorStoreProvider, request.app.state.vector_store)


def _embedding_model(request: Request) -> EmbeddingModel:
    model = request.app.state.embedding_model
    if model is None:
        model = build_default_llm_provider(
            config_path=request.app.state.project_config_path
        ).create_embedding_model()
        request.app.state.embedding_model = model
    return cast(EmbeddingModel, model)


def _rerank_model(request: Request) -> RerankModel:
    model = request.app.state.rerank_model
    if model is None:
        model = _llm_provider(request).create_rerank_model()
        request.app.state.rerank_model = model
    return cast(RerankModel, model)


def _llm_provider(request: Request) -> LlmProvider:
    provider = request.app.state.llm_provider
    if provider is None:
        provider = build_default_llm_provider(config_path=request.app.state.project_config_path)
        request.app.state.llm_provider = provider
    return cast(LlmProvider, provider)


def _context_window_tokens(request: Request) -> int:
    cached = getattr(request.app.state, "llm_context_window_tokens", None)
    if isinstance(cached, int):
        return cached
    resolved = load_llm_provider_config(
        config_path=request.app.state.project_config_path
    ).context_window_tokens
    request.app.state.llm_context_window_tokens = resolved
    return resolved


def _chat_memory_service(request: Request) -> ChatMemoryService:
    return ChatMemoryService(
        repositories=_memory_repositories(request),
        llm_provider=_llm_provider(request),
        context_window_tokens=_context_window_tokens(request),
    )


async def _chat_memory_context(
    request: Request, *, owner_user_id: str
) -> tuple[ChatMemoryService, str]:
    service = _chat_memory_service(request)
    prompt_builder = ChatStreamingService(
        repositories=_memory_repositories(request),
        agent_runner=_chat_agent_runner(request),
        memory_service=service,
    )
    return service, await prompt_builder.build_system_prompt(owner_user_id=owner_user_id)


def _chat_agent_runner(request: Request) -> ChatAgentRunner:
    runner = request.app.state.chat_agent_runner
    if runner is None:
        retrieval_tool = KnowledgeRetrievalTool(
            embedding_model=_embedding_model(request),
            vector_store=cast(RetrievalVectorStore, _vector_store(request)),
            rerank_model=_rerank_model(request),
            lexical_cache=cast(LexicalIndexCache, request.app.state.lexical_index_cache),
            document_repository=_memory_repositories(request).documents,
        )
        runner = LangChainChatAgentRunner(
            llm_provider=_llm_provider(request),
            retrieval_tool=retrieval_tool,
            mcp_client_provider=_mcp_connection_service(request),
        )
        request.app.state.chat_agent_runner = runner
    return cast(ChatAgentRunner, runner)


def _mcp_client(request: Request) -> LocalMcpClient:
    config = project_config_section("mcp", config_path=request.app.state.project_config_path)
    return LocalMcpClient(
        required_str(config, "clsSseUrl"),
        timeout_seconds=required_int(config, "timeoutSeconds"),
        retries=required_int(config, "retries"),
    )


def _active_alert_provider(request: Request) -> ActiveAlertProvider:
    provider = cast(ActiveAlertProvider | None, request.app.state.alert_provider)
    if provider is None:
        provider = build_alertmanager_alert_provider(
            config_path=request.app.state.project_config_path
        )
        request.app.state.alert_provider = provider
    return provider


def _event_ingestion_settings(request: Request) -> EventIngestionSettings:
    settings = cast(
        EventIngestionSettings | None,
        request.app.state.event_ingestion_settings,
    )
    if settings is None:
        settings = load_event_ingestion_settings(config_path=request.app.state.project_config_path)
        request.app.state.event_ingestion_settings = settings
    return settings


def _alert_event_publisher(request: Request) -> EventPublisher:
    publisher = cast(EventPublisher | None, request.app.state.alert_event_publisher)
    if publisher is None:
        publisher = KafkaEventPublisher(_event_ingestion_settings(request))
        request.app.state.alert_event_publisher = publisher
    return publisher


def _workflow_checkpoint_store(request: Request) -> WorkflowCheckpointStore:
    store = cast(
        WorkflowCheckpointStore | None,
        request.app.state.workflow_checkpoint_store,
    )
    if store is None:
        settings = _event_ingestion_settings(request)
        store = RedisWorkflowCheckpointStore(
            settings.redis_url,
            retention_seconds=settings.event_retention_seconds,
        )
        request.app.state.workflow_checkpoint_store = store
    return store


def _aiops_diagnostic_runner(request: Request) -> AiopsDiagnosticRunner:
    runner = cast(AiopsDiagnosticRunner | None, request.app.state.aiops_diagnostic_runner)
    if runner is None:
        cls_log_config = project_config_section(
            "clsLogUpload",
            config_path=request.app.state.project_config_path,
        )
        runner = AiopsDiagnosticService(
            repositories=_memory_repositories(request),
            llm_provider=_llm_provider(request),
            retrieval_tool=KnowledgeRetrievalTool(
                embedding_model=_embedding_model(request),
                vector_store=cast(RetrievalVectorStore, _vector_store(request)),
                rerank_model=_rerank_model(request),
                lexical_cache=cast(LexicalIndexCache, request.app.state.lexical_index_cache),
                document_repository=_memory_repositories(request).documents,
            ),
            mcp_client_provider=_mcp_connection_service(request),
            cls_region=required_str(cls_log_config, "region"),
            cls_topic_id=required_str(cls_log_config, "topicId"),
            case_persistor=DiagnosisCasePersistor(
                repositories=_memory_repositories(request),
                index_task_scheduler=_index_task_scheduler(request),
            ),
            checkpoint_store=_workflow_checkpoint_store(request),
        )
        request.app.state.aiops_diagnostic_runner = runner
    return runner


def _document_indexing_service(request: Request) -> DocumentIndexingService:
    return DocumentIndexingService(
        repositories=_memory_repositories(request),
        embedding_model=_embedding_model(request),
        vector_store=_document_vector_store(request),
    )


def _document_indexing_service_from_app(app: FastAPI) -> DocumentIndexingService:
    return DocumentIndexingService(
        repositories=cast(MemoryRepositories, app.state.memory_repositories),
        embedding_model=cast(EmbeddingModel, app.state.embedding_model)
        if app.state.embedding_model is not None
        else build_default_llm_provider(
            config_path=app.state.project_config_path
        ).create_embedding_model(),
        vector_store=cast(DocumentVectorStoreProvider, app.state.vector_store),
    )


def _index_task_scheduler(request: Request) -> DocumentIndexTaskScheduler:
    return cast(DocumentIndexTaskScheduler, request.app.state.index_task_scheduler)


def _chat_session_payload(
    record: ChatSessionRecord, context_window_tokens: int
) -> dict[str, object]:
    return {
        "id": record.id,
        "ownerUserId": record.owner_user_id,
        "title": record.title or "New chat",
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
        "memory": memory_payload(record, context_window_tokens),
    }


def _chat_message_payload(message: ChatMessageRecord) -> dict[str, object]:
    return {
        "id": message.id,
        "ownerUserId": message.owner_user_id,
        "sessionId": message.session_id,
        "role": message.role,
        "content": message.content,
        "metadata": message.metadata,
        "createdAt": message.created_at.isoformat(),
    }


def _agent_tool_call_audit_payload(record: AgentToolCallAuditRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "ownerUserId": record.owner_user_id,
        "sessionId": record.chat_session_id,
        "diagnosticTaskId": record.diagnostic_task_id,
        "toolName": record.tool_name,
        "status": record.status,
        "arguments": record.arguments,
        "resultSummary": record.result_summary,
        "errorMessage": record.error_message,
        "startedAt": record.started_at.isoformat(),
        "completedAt": record.completed_at.isoformat() if record.completed_at is not None else None,
        "durationMs": record.duration_ms,
        "createdAt": record.created_at.isoformat(),
    }


def _normalize_chat_title(title: str | None) -> str:
    if title is None:
        return "New chat"
    normalized = " ".join(title.split())
    if normalized == "":
        return "New chat"
    return normalized[:80]


async def _maybe_generate_chat_title(
    repositories: MemoryRepositories,
    *,
    user_id: str,
    session: ChatSessionRecord,
    message_role: str,
    message_content: str,
) -> ChatSessionRecord:
    if message_role != "user" or session.title not in {None, "New chat"}:
        refreshed = await repositories.chat.get_session(
            owner_user_id=user_id,
            session_id=session.id,
        )
        return refreshed or session
    generated_title = _normalize_chat_title(message_content)
    updated = await repositories.chat.update_session_title(
        owner_user_id=user_id,
        session_id=session.id,
        title=generated_title,
    )
    return updated or session


def _diagnostic_task_payload(
    record: DiagnosticTaskRecord,
    *,
    reports: Sequence[DiagnosticReportRecord] = (),
) -> dict[str, object]:
    return {
        "id": record.id,
        "ownerUserId": record.owner_user_id,
        "status": record.status,
        "query": record.query,
        "inputPayload": record.input_payload,
        "resultPayload": record.result_payload,
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
        "completedAt": record.completed_at.isoformat() if record.completed_at is not None else None,
        "reports": [_diagnostic_report_payload(report) for report in reports],
    }


def _active_alert_payload(alert: ActiveAlert) -> dict[str, object]:
    return {
        "id": alert.id,
        "source": alert.source,
        "alertName": alert.alert_name,
        "service": alert.service,
        "severity": alert.severity,
        "status": alert.status,
        "startsAt": alert.starts_at,
        "summary": alert.summary,
        "labels": alert.labels,
        "annotations": alert.annotations,
        "context": alert.context,
    }


def _diagnostic_report_payload(
    record: DiagnosticReportRecord,
    *,
    evidence_ids: Sequence[str] = (),
) -> dict[str, object]:
    return {
        "id": record.id,
        "title": record.title,
        "content": record.content,
        "payload": record.payload,
        "evidenceIds": list(evidence_ids),
        "createdAt": record.created_at.isoformat(),
    }


def _diagnostic_case_payload(record: DiagnosticCaseRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "ownerUserId": record.owner_user_id,
        "taskId": record.task_id,
        "reportId": record.report_id,
        "documentId": record.document_id,
        "indexTaskId": record.index_task_id,
        "alertName": record.alert_name,
        "service": record.service,
        "keywords": record.keywords,
        "rootCause": record.root_cause,
        "remediation": record.remediation,
        "summary": record.summary,
        "evidenceIds": record.evidence_ids,
        "createdAt": record.created_at.isoformat(),
    }


def _diagnostic_step_payload(record: DiagnosticStepRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "taskId": record.task_id,
        "sequence": record.sequence,
        "phase": record.phase,
        "status": record.status,
        "payload": record.payload,
        "createdAt": record.created_at.isoformat(),
    }


def _diagnostic_evidence_payload(record: DiagnosticEvidenceRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "taskId": record.task_id,
        "stepId": record.step_id,
        "toolCallId": record.tool_call_id,
        "kind": record.kind,
        "source": record.source,
        "summary": record.summary,
        "payload": record.payload,
        "createdAt": record.created_at.isoformat(),
    }


def _diagnostic_case_content(
    task: DiagnosticTaskRecord,
    report: DiagnosticReportRecord,
    evidence: Sequence[DiagnosticEvidenceRecord],
) -> str:
    lines = [
        "# AIOps Diagnostic Case",
        "",
        f"Diagnostic task: {task.id}",
        f"Report: {report.id}",
        "",
        "## Incident query",
        task.query,
        "",
        "## Evidence-backed report",
        report.content,
        "",
        "## Evidence summaries",
    ]
    lines.extend(f"- [{item.kind}] {item.source}: {item.summary[:500]}" for item in evidence)
    return "\n".join(lines)


def _report_evidence_link_payload(record: ReportEvidenceLinkRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "taskId": record.task_id,
        "reportId": record.report_id,
        "evidenceId": record.evidence_id,
        "createdAt": record.created_at.isoformat(),
    }


def _graph_checkpoint_payload(record: GraphCheckpointRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "taskId": record.task_id,
        "threadId": record.thread_id,
        "checkpointNamespace": record.checkpoint_ns,
        "checkpointId": record.checkpoint_id,
        "payload": record.checkpoint_payload,
        "metadata": record.metadata,
        "createdAt": record.created_at.isoformat(),
    }


def _remediation_approval_payload(
    record: RemediationApprovalRecord,
) -> dict[str, object]:
    return {
        "id": record.id,
        "ownerUserId": record.owner_user_id,
        "diagnosticId": record.task_id,
        "toolName": record.tool_name,
        "arguments": record.arguments,
        "rationale": record.rationale,
        "riskLevel": record.risk_level,
        "status": record.status,
        "decisionNote": record.decision_note,
        "decidedByUserId": record.decided_by_user_id,
        "decidedAt": record.decided_at.isoformat() if record.decided_at else None,
        "dispatchStatus": record.dispatch_status,
        "dispatchError": record.dispatch_error,
        "dispatchedAt": record.dispatched_at.isoformat() if record.dispatched_at else None,
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
    }


def _report_evidence_ids(
    links: Sequence[ReportEvidenceLinkRecord],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for link in links:
        result.setdefault(link.report_id, []).append(link.evidence_id)
    return result


def _knowledge_document_payload(record: KnowledgeDocumentRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "knowledgeBaseId": record.knowledge_base_id,
        "ownerUserId": record.owner_user_id,
        "filename": record.filename,
        "sizeBytes": record.size_bytes,
        "mimeType": record.mime_type,
        "contentHash": record.content_hash,
        "status": record.status,
        "indexStatus": record.index_status,
        "chunking": _document_chunking_payload(record),
        "uploadedAt": record.uploaded_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
        "source": record.source,
    }


def _document_chunking_payload(record: KnowledgeDocumentRecord) -> dict[str, object]:
    chunking = record.metadata.get("chunking")
    if isinstance(chunking, dict):
        return cast(dict[str, object], chunking)
    return {
        "strategy": "fixed-character",
        "maxCharacters": DEFAULT_CHUNK_SIZE,
        "overlapCharacters": DEFAULT_CHUNK_OVERLAP,
    }


def _parse_chunking_configuration(raw: str) -> dict[str, object]:
    default: dict[str, object] = {
        "strategy": "fixed-character",
        "maxCharacters": DEFAULT_CHUNK_SIZE,
        "overlapCharacters": DEFAULT_CHUNK_OVERLAP,
    }
    if not raw.strip():
        return default
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiErrorException("VALIDATION_INVALID_ARGUMENT") from exc
    if not isinstance(value, dict):
        raise ApiErrorException("VALIDATION_INVALID_ARGUMENT")
    mapping = cast(dict[str, object], value)
    strategy = mapping.get("strategy")
    if strategy not in {"fixed-character", "markdown-heading", "paragraph"}:
        raise ApiErrorException(
            "VALIDATION_INVALID_ARGUMENT",
            "分片策略只能是 fixed-character、markdown-heading 或 paragraph。",
        )
    if strategy != "fixed-character":
        return {"strategy": strategy}
    size = mapping.get("maxCharacters")
    overlap = mapping.get("overlapCharacters")
    if (
        not isinstance(size, int)
        or not isinstance(overlap, int)
        or size < 100
        or size > 5000
        or overlap < 0
        or overlap >= size
    ):
        raise ApiErrorException(
            "VALIDATION_INVALID_ARGUMENT",
            "固定字符分片需要 100-5000 的最大字符数，且 overlap 必须大于等于 0 并小于最大字符数。",
        )
    return {"strategy": strategy, "maxCharacters": size, "overlapCharacters": overlap}


def _runtime_chunk_size(configuration: dict[str, object]) -> int:
    if configuration.get("strategy") == "fixed-character":
        return cast(int, configuration["maxCharacters"])
    return DEFAULT_CHUNK_SIZE


def _runtime_chunk_overlap(configuration: dict[str, object]) -> int:
    if configuration.get("strategy") == "fixed-character":
        return cast(int, configuration["overlapCharacters"])
    return 0


def _decode_indexable_document(record: KnowledgeDocumentRecord) -> str:
    value = record.metadata.get("indexableText")
    return value if isinstance(value, str) else ""


def _chat_configuration_repository(request: Request) -> UserChatConfigurationRepository:
    repository = _memory_repositories(request).chat_configurations
    if repository is None:
        raise ApiErrorException("SYSTEM_INTERNAL_ERROR")
    return repository


def _chat_prompt_repository(request: Request) -> UserChatPromptRepository:
    repository = _memory_repositories(request).chat_prompts
    if repository is None:
        raise ApiErrorException("SYSTEM_INTERNAL_ERROR")
    return repository


def _chat_skill_repository(request: Request) -> UserChatSkillRepository:
    repository = _memory_repositories(request).chat_skills
    if repository is None:
        raise ApiErrorException("SYSTEM_INTERNAL_ERROR")
    return repository


async def _read_chat_configuration(
    request: Request,
    *,
    owner_user_id: str,
) -> tuple[list[UserChatPromptRecord], list[UserChatSkillRecord], UserChatConfigurationRecord]:
    prompt_repository = _chat_prompt_repository(request)
    skill_repository = _chat_skill_repository(request)
    configuration_repository = _chat_configuration_repository(request)
    default_prompt = await prompt_repository.ensure_default(
        owner_user_id=owner_user_id,
        label=DEFAULT_CHAT_PROMPT_LABEL,
        content=DEFAULT_CHAT_PROMPT_CONTENT,
    )
    configuration = await configuration_repository.get_or_create(
        owner_user_id=owner_user_id,
        system_prompt_id=default_prompt.id,
        skill_ids=[],
    )
    prompts = await prompt_repository.list(owner_user_id=owner_user_id)
    prompt_ids = {item.id for item in prompts}
    if configuration.system_prompt_id not in prompt_ids:
        configuration = await configuration_repository.update(
            owner_user_id=owner_user_id,
            system_prompt_id=default_prompt.id,
            skill_ids=configuration.skill_ids,
        )
    skills = await skill_repository.list(owner_user_id=owner_user_id)
    available_skill_ids = {item.id for item in skills}
    selected_skill_ids = [
        item for item in dict.fromkeys(configuration.skill_ids) if item in available_skill_ids
    ]
    if selected_skill_ids != configuration.skill_ids:
        configuration = await configuration_repository.update(
            owner_user_id=owner_user_id,
            system_prompt_id=configuration.system_prompt_id,
            skill_ids=selected_skill_ids,
        )
    return prompts, skills, configuration


def _chat_configuration_payload(
    prompts: list[UserChatPromptRecord],
    skills: list[UserChatSkillRecord],
    configuration: UserChatConfigurationRecord,
) -> dict[str, object]:
    return {
        "prompts": [_chat_prompt_payload(item) for item in prompts],
        "skills": [_chat_skill_payload(item) for item in skills],
        "selection": {
            "systemPromptId": configuration.system_prompt_id,
            "skillIds": configuration.skill_ids,
            "updatedAt": configuration.updated_at.isoformat(),
        },
    }


def _chat_prompt_payload(prompt: UserChatPromptRecord) -> dict[str, object]:
    return {
        "id": prompt.id,
        "label": prompt.label,
        "content": prompt.content,
        "isDefault": prompt.is_default,
        "createdAt": prompt.created_at.isoformat(),
        "updatedAt": prompt.updated_at.isoformat(),
    }


def _chat_skill_payload(skill: UserChatSkillRecord) -> dict[str, object]:
    return {
        "id": skill.id,
        "filename": skill.filename,
        "name": skill.name,
        "description": skill.description,
        "label": skill.name,
        "contentPreview": skill.description,
        "sizeBytes": skill.size_bytes,
        "createdAt": skill.created_at.isoformat(),
        "updatedAt": skill.updated_at.isoformat(),
    }


def _document_index_task_payload(record: DocumentIndexTaskRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "ownerUserId": record.owner_user_id,
        "knowledgeBaseId": record.knowledge_base_id,
        "documentId": record.document_id,
        "status": record.status,
        "failureReason": record.failure_reason,
        "retryOfTaskId": record.retry_of_task_id,
        "createdAt": record.created_at.isoformat(),
        "updatedAt": record.updated_at.isoformat(),
        "startedAt": record.started_at.isoformat() if record.started_at is not None else None,
        "completedAt": record.completed_at.isoformat() if record.completed_at is not None else None,
    }


def _milvus_health_payload(result: MilvusHealthCheckResult) -> dict[str, object]:
    return {
        "ok": result.ok,
        "uri": result.uri,
        "collectionName": result.collection_name,
        "latencyMs": result.latency_ms,
        "error": result.error,
    }


def _ensure_knowledge_base_access(user: UserRecord, knowledge_base_id: str) -> None:
    if knowledge_base_id != f"kb_{user.id}":
        raise ApiErrorException("AUTH_FORBIDDEN")


def _accessible_knowledge_base_ids(user: UserRecord) -> tuple[str, ...]:
    return (f"kb_{user.id}",)


def _validate_upload(file: UploadFile, content: bytes) -> None:
    filename = file.filename or ""
    suffix = PurePosixPath(filename).suffix.lower()
    mime_type = file.content_type or ""
    display_mime_type = mime_type or "empty"
    if not content:
        raise ApiErrorException(
            "VALIDATION_INVALID_ARGUMENT",
            "文件不能为空，请上传包含正文的 Markdown 或 PDF。",
        )
    if len(content) > DOCUMENT_MAX_SIZE_BYTES:
        raise ApiErrorException("VALIDATION_INVALID_ARGUMENT", "文件大小不能超过 10 MB。")
    if suffix not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise ApiErrorException(
            "VALIDATION_INVALID_ARGUMENT",
            "仅支持 Markdown(.md) 与 PDF(.pdf) 文件。",
        )
    if suffix == ".md" and mime_type not in MARKDOWN_DOCUMENT_MIME_TYPES:
        raise ApiErrorException(
            "VALIDATION_INVALID_ARGUMENT",
            f"Markdown 文件的 MIME 类型不符合要求：{display_mime_type}。请上传 .md 文件。",
        )
    if suffix == ".pdf" and mime_type not in PDF_DOCUMENT_MIME_TYPES:
        raise ApiErrorException(
            "VALIDATION_INVALID_ARGUMENT",
            f"PDF 文件的 MIME 类型不符合要求：{display_mime_type}。请上传有效的 .pdf 文件。",
        )


def _delete_document_vectors(
    request: Request,
    *,
    tenant_id: str,
    knowledge_base_id: str,
    document_id: str,
) -> None:
    try:
        _document_vector_store(request).delete_document_chunks(
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
        )
    except ApiErrorException:
        raise
    except Exception as exc:
        raise ApiErrorException("SYSTEM_INTERNAL_ERROR") from exc
