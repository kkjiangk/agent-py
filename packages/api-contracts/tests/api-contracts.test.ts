import { describe, expect, it } from "vitest";

import {
  API_ERROR_CODES,
  DOCUMENT_UPLOAD_POLICY,
  OPENAPI_CONTRACT,
  SSE_EVENT_TYPES,
  type AuthTokenResponse,
  type AuthUser,
  type AppendChatMessageRequest,
  type ChatMessage,
  type ChatMessageMetadata,
  type ChatStreamCompleteResult,
  type ChatSessionDetailResponse,
  type ChatToolCallAuditListResponse,
  type ChatSessionListResponse,
  type ChatSessionSummary,
  type ChatSessionMutationResponse,
  type ClearChatSessionResponse,
  type CreateDocumentIndexTaskResponse,
  type DocumentIndexTask,
  KNOWLEDGE_RETRIEVAL_TOOL_NAME,
  KNOWLEDGE_RETRIEVAL_TOP_K_LIMITS,
  buildMilvusTenantFilter,
  buildErrorResponse,
  buildSuccessResponse,
  buildVectorChunkMetadata,
  type ApiErrorResponse,
  type ApiSuccessResponse,
  type BackgroundJob,
  type LoginRequest,
  type RegisterRequest,
  type KnowledgeDocument,
  type KnowledgeDocumentUploadResponse,
  type KnowledgeRetrievalCitationSource,
  type KnowledgeRetrievalHit,
  type KnowledgeRetrievalToolInput,
  type KnowledgeRetrievalToolOutput,
  type McpConnection,
  type UpsertFeedbackRequest,
  type RetryDocumentIndexTaskResponse,
  type StreamChatMessageRequest,
  type VectorChunkMetadata,
  type ToolCallSseEvent,
  type ToolCallAudit,
  type SseEvent
} from "../src";

describe("HTTP response contracts", () => {
  it("wraps successful responses with metadata", () => {
    const response: ApiSuccessResponse<{ id: string }> = buildSuccessResponse(
      { id: "chat_123" },
      { requestId: "req_123" }
    );

    expect(response).toEqual({
      ok: true,
      data: { id: "chat_123" },
      meta: { requestId: "req_123" }
    });
  });

  it("wraps business, validation, and system errors with shared shape", () => {
    const response: ApiErrorResponse = buildErrorResponse("VALIDATION_INVALID_ARGUMENT", {
      requestId: "req_456",
      details: [
        {
          code: "required",
          message: "message is required",
          path: ["message"]
        }
      ]
    });

    expect(response.ok).toBe(false);
    expect(response.error.category).toBe("validation");
    expect(response.error.httpStatus).toBe(400);
    expect(response.error.details?.[0]?.path).toEqual(["message"]);
  });

  it("documents separate liveness, readiness, and safe configuration checks", () => {
    expect(OPENAPI_CONTRACT.paths["/health"]?.get).toBeDefined();
    expect(OPENAPI_CONTRACT.paths["/ready"]?.get).toBeDefined();
    expect(OPENAPI_CONTRACT.paths["/config/check"]?.get).toBeDefined();
    expect(OPENAPI_CONTRACT.paths["/readiness"]).toBeUndefined();
  });

  it("documents background job, feedback, and MCP connection APIs", () => {
    expect(OPENAPI_CONTRACT.paths["/background-jobs"]?.get).toBeDefined();
    expect(OPENAPI_CONTRACT.paths["/feedback"]?.post).toBeDefined();
    expect(OPENAPI_CONTRACT.paths["/mcp/connections"]?.get).toBeDefined();
    expect(OPENAPI_CONTRACT.paths["/mcp/connections/{connectionId}:check"]?.post).toBeDefined();

    const job: BackgroundJob = {
      id: "job_1",
      ownerUserId: "user_1",
      kind: "document_index",
      resourceType: "document_index_task",
      resourceId: "index_1",
      status: "queued",
      attempt: 0,
      maxAttempts: 3,
      timeoutSeconds: 900,
      availableAt: "2026-07-11T00:00:00Z",
      cancelRequestedAt: null,
      retryOfJobId: null,
      errorMessage: null,
      createdAt: "2026-07-11T00:00:00Z",
      updatedAt: "2026-07-11T00:00:00Z",
      startedAt: null,
      completedAt: null
    };
    const feedback: UpsertFeedbackRequest = {
      targetType: "chat_message",
      targetId: "message_1",
      rating: "positive"
    };
    const connection: McpConnection = {
      id: "mcp_1",
      ownerUserId: "user_1",
      name: "腾讯云 CLS",
      transport: "sse",
      url: "http://127.0.0.1:3000/sse",
      enabled: true,
      timeoutSeconds: 15,
      retries: 1,
      lastCheck: null,
      createdAt: "2026-07-11T00:00:00Z",
      updatedAt: "2026-07-11T00:00:00Z"
    };

    expect(job.status).toBe("queued");
    expect(feedback.rating).toBe("positive");
    expect(connection.transport).toBe("sse");
  });
});

describe("error code catalog", () => {
  it("contains stable codes with categories, statuses, and messages", () => {
    expect(API_ERROR_CODES.BUSINESS_CONFLICT).toMatchObject({
      category: "business",
      httpStatus: 409,
      message: expect.any(String)
    });
    expect(API_ERROR_CODES.SYSTEM_INTERNAL_ERROR).toMatchObject({
      category: "system",
      httpStatus: 500,
      message: expect.any(String)
    });
    expect(API_ERROR_CODES.AUTH_UNAUTHENTICATED).toMatchObject({
      category: "auth",
      httpStatus: 401,
      message: expect.any(String)
    });
    expect(API_ERROR_CODES.AUTH_INVALID_CREDENTIALS).toMatchObject({
      category: "auth",
      httpStatus: 401,
      message: expect.stringContaining("credentials")
    });
    expect(API_ERROR_CODES.AUTH_FORBIDDEN).toMatchObject({
      category: "auth",
      httpStatus: 403,
      message: expect.stringContaining("permission")
    });
  });
});

describe("vector tenant contracts", () => {
  it("builds Milvus chunk metadata with owner and tenant scope", () => {
    const metadata: VectorChunkMetadata = buildVectorChunkMetadata({
      ownerUserId: "user_1",
      tenantId: "user_1",
      knowledgeBaseId: "kb_1",
      documentId: "doc_1",
      chunkId: "chunk_1"
    });

    expect(metadata).toEqual({
      ownerUserId: "user_1",
      tenantId: "user_1",
      knowledgeBaseId: "kb_1",
      documentId: "doc_1",
      chunkId: "chunk_1"
    });
  });

  it("builds retrieval filters from tenant scope and accessible knowledge bases", () => {
    expect(
      buildMilvusTenantFilter({
        tenantId: "user_1",
        knowledgeBaseIds: ["kb_1", "kb_2"]
      })
    ).toBe('tenantId == "user_1" && knowledgeBaseId in ["kb_1","kb_2"]');
  });
});

describe("auth contracts", () => {
  it("exports shared auth request and response shapes", () => {
    const registerRequest: RegisterRequest = {
      email: "timi@example.com",
      displayName: "Timi",
      password: "correct horse battery staple"
    };
    const loginRequest: LoginRequest = {
      email: registerRequest.email,
      password: registerRequest.password
    };
    const user: AuthUser = {
      id: "user_1",
      email: registerRequest.email,
      displayName: registerRequest.displayName,
      createdAt: "2026-07-08T00:00:00.000Z"
    };
    const tokenResponse: AuthTokenResponse = {
      user,
      accessToken: "opaque-token",
      tokenType: "bearer"
    };

    expect(loginRequest.email).toBe("timi@example.com");
    expect(tokenResponse.user.displayName).toBe("Timi");
  });
});

describe("knowledge document contracts", () => {
  it("exports document metadata shapes and upload policy", () => {
    const document: KnowledgeDocument = {
      id: "doc_1",
      knowledgeBaseId: "kb_1",
      ownerUserId: "user_1",
      filename: "runbook.md",
      sizeBytes: 128,
      mimeType: "text/markdown",
      contentHash: "sha256:abc",
      status: "ready",
      indexStatus: "pending",
      uploadedAt: "2026-07-09T00:00:00.000Z",
      updatedAt: "2026-07-09T00:00:00.000Z"
    };
    const response: KnowledgeDocumentUploadResponse = {
      document,
      duplicateOfDocumentId: null,
      overwrite: false
    };

    expect(response.document.filename).toBe("runbook.md");
    expect(DOCUMENT_UPLOAD_POLICY.maxSizeBytes).toBeGreaterThan(0);
    expect(DOCUMENT_UPLOAD_POLICY.allowedMimeTypes).toContain("text/markdown");
    expect(DOCUMENT_UPLOAD_POLICY.allowedExtensions).toContain(".md");
    expect(DOCUMENT_UPLOAD_POLICY.allowedExtensions).toContain(".pdf");
    expect(DOCUMENT_UPLOAD_POLICY.allowedExtensions).not.toContain(".csv");
    expect(DOCUMENT_UPLOAD_POLICY.allowedExtensions).not.toContain(".json");
    expect(DOCUMENT_UPLOAD_POLICY.allowedExtensions).not.toContain(".txt");
    expect(DOCUMENT_UPLOAD_POLICY.duplicateWithoutOverwrite).toBe("conflict");
  });
});

describe("document indexing contracts", () => {
  it("exports index task shapes and statuses", () => {
    const task: DocumentIndexTask = {
      id: "index_task_1",
      ownerUserId: "user_1",
      knowledgeBaseId: "kb_1",
      documentId: "doc_1",
      status: "failed",
      failureReason: "embedding unavailable",
      retryOfTaskId: null,
      createdAt: "2026-07-09T00:00:00.000Z",
      updatedAt: "2026-07-09T00:00:01.000Z",
      startedAt: "2026-07-09T00:00:00.500Z",
      completedAt: "2026-07-09T00:00:01.000Z"
    };
    const createResponse: CreateDocumentIndexTaskResponse = {
      task,
      scheduled: true
    };
    const retryResponse: RetryDocumentIndexTaskResponse = {
      task: { ...task, id: "index_task_2", status: "pending", retryOfTaskId: task.id },
      retriedFromTaskId: task.id,
      scheduled: true
    };

    expect(createResponse.task.status).toBe("failed");
    expect(retryResponse.task.retryOfTaskId).toBe("index_task_1");
  });
});

describe("chat session contracts", () => {
  it("exports shared session, message, metadata, and mutation shapes", () => {
    const metadata: ChatMessageMetadata = {
      citations: [
        {
          id: "chunk_1",
          title: "runbook.md",
          sourceType: "knowledge-base",
          chunkId: "chunk_1",
          documentId: "doc_1",
          knowledgeBaseId: "kb_1",
          source: "runbook.md",
          metadata: { section: "restart" },
          score: 0.91
        }
      ],
      toolCallIds: ["tool_call_1"],
      custom: { latencyMs: 42 }
    };
    const message: ChatMessage = {
      id: "message_1",
      ownerUserId: "user_1",
      sessionId: "chat_1",
      role: "assistant",
      content: "Use the restart runbook.",
      metadata,
      createdAt: "2026-07-09T00:00:00.000Z"
    };
    const session: ChatSessionSummary = {
      id: "chat_1",
      ownerUserId: "user_1",
      title: "Restart API",
      createdAt: "2026-07-09T00:00:00.000Z",
      updatedAt: "2026-07-09T00:00:01.000Z"
    };
    const detail: ChatSessionDetailResponse = {
      session,
      messages: [message]
    };
    const list: ChatSessionListResponse = {
      items: [session]
    };
    const appendRequest: AppendChatMessageRequest = {
      role: "user",
      content: "How do I restart the API?",
      metadata: { custom: { source: "manual" } }
    };
    const mutation: ChatSessionMutationResponse = {
      session,
      message
    };
    const clearResponse: ClearChatSessionResponse = {
      sessionId: session.id,
      cleared: true,
      deletedMessages: 2
    };

    expect(detail.messages[0]?.metadata.citations?.[0]?.chunkId).toBe("chunk_1");
    expect(list.items[0]?.updatedAt).toBe("2026-07-09T00:00:01.000Z");
    expect(appendRequest.role).toBe("user");
    expect(mutation.message?.metadata.toolCallIds).toEqual(["tool_call_1"]);
    expect(clearResponse.deletedMessages).toBe(2);
  });

  it("exports the persisted chat tool-call audit collection", () => {
    const audit: ToolCallAudit = {
      id: "tool_call_1",
      ownerUserId: "user_1",
      sessionId: "chat_1",
      diagnosticTaskId: null,
      toolName: "knowledge_retrieval",
      status: "completed",
      arguments: { query: "restart api" },
      resultSummary: '{"results":["chunk_1"]}',
      errorMessage: null,
      startedAt: "2026-07-10T00:00:00.000Z",
      completedAt: "2026-07-10T00:00:00.450Z",
      durationMs: 450,
      createdAt: "2026-07-10T00:00:00.000Z"
    };
    const response: ChatToolCallAuditListResponse = { items: [audit] };

    expect(response.items[0]?.durationMs).toBe(450);
    expect(OPENAPI_CONTRACT.paths["/chat/sessions/{sessionId}/tool-call-audits"]?.get?.operationId).toBe(
      "listChatToolCallAudits"
    );
  });

  it("exports streaming chat request and completion result shapes", () => {
    const request: StreamChatMessageRequest = {
      content: "How do I restart the API?",
      metadata: {
        custom: { source: "composer" }
      }
    };
    const session: ChatSessionSummary = {
      id: "chat_1",
      ownerUserId: "user_1",
      title: "Restart API",
      createdAt: "2026-07-09T00:00:00.000Z",
      updatedAt: "2026-07-09T00:00:01.000Z"
    };
    const message: ChatMessage = {
      id: "message_2",
      ownerUserId: "user_1",
      sessionId: session.id,
      role: "assistant",
      content: "Use the restart runbook.",
      metadata: {
        citations: [
          {
            id: "chunk_1",
            title: "runbook.md",
            sourceType: "knowledge-base",
            chunkId: "chunk_1",
            documentId: "doc_1",
            knowledgeBaseId: "kb_1",
            source: "runbook.md",
            metadata: { section: "restart" },
            score: 0.91
          }
        ],
        toolCallIds: ["tool_call_1"]
      },
      createdAt: "2026-07-09T00:00:02.000Z"
    };
    const result: ChatStreamCompleteResult = {
      session,
      message
    };

    expect(request.content).toContain("restart");
    expect(result.message.metadata.citations?.[0]?.documentId).toBe("doc_1");
  });
});

describe("knowledge retrieval contracts", () => {
  it("exports agent tool input, output, hit, citation, and empty result shapes", () => {
    const input: KnowledgeRetrievalToolInput = {
      query: "how do I restart the API?",
      topK: 3,
      filters: {
        knowledgeBaseIds: ["kb_1"],
        documentIds: ["doc_1"],
        metadata: { environment: "prod" }
      }
    };
    const hit: KnowledgeRetrievalHit = {
      chunkId: "chunk_1",
      documentId: "doc_1",
      knowledgeBaseId: "kb_1",
      ownerUserId: "user_1",
      tenantId: "user_1",
      content: "Restart the API deployment from the runbook.",
      source: "runbook.md",
      metadata: { section: "restart" },
      score: 0.94,
      vectorRank: 2,
      bm25Rank: 1,
      rerankRank: 1,
      vectorScore: 0.87,
      bm25Score: 4.21,
      rrfScore: 2 / 61,
      rerankScore: 0.94
    };
    const citation: KnowledgeRetrievalCitationSource = {
      id: "chunk_1",
      title: "runbook.md",
      sourceType: "knowledge-base",
      chunkId: hit.chunkId,
      documentId: hit.documentId,
      knowledgeBaseId: hit.knowledgeBaseId,
      source: hit.source,
      metadata: hit.metadata,
      score: hit.score,
      vectorRank: hit.vectorRank,
      bm25Rank: hit.bm25Rank,
      rerankRank: hit.rerankRank,
      vectorScore: hit.vectorScore,
      bm25Score: hit.bm25Score,
      rrfScore: hit.rrfScore,
      rerankScore: hit.rerankScore
    };
    const output: KnowledgeRetrievalToolOutput = {
      query: input.query,
      topK: 3,
      results: [hit],
      citations: [citation]
    };
    const emptyOutput: KnowledgeRetrievalToolOutput = {
      query: "unknown",
      topK: KNOWLEDGE_RETRIEVAL_TOP_K_LIMITS.default,
      results: [],
      citations: []
    };

    expect(KNOWLEDGE_RETRIEVAL_TOOL_NAME).toBe("knowledge_retrieval");
    expect(KNOWLEDGE_RETRIEVAL_TOP_K_LIMITS.max).toBe(5);
    expect(output.results[0]?.metadata.section).toBe("restart");
    expect(output.citations[0]?.documentId).toBe("doc_1");
    expect(emptyOutput.results).toEqual([]);
  });
});

describe("SSE event contracts", () => {
  it("defines every required event type", () => {
    expect(SSE_EVENT_TYPES).toEqual([
      "content.delta",
      "reasoning.delta",
      "tool.call",
      "reference.source",
      "task.status",
      "report",
      "complete",
      "error"
    ]);
  });

  it("reuses structured errors for streaming failures", () => {
    const event: SseEvent = {
      id: "evt_1",
      type: "error",
      channel: "chat",
      timestamp: "2026-07-08T00:00:00.000Z",
      error: buildErrorResponse("SYSTEM_INTERNAL_ERROR", { requestId: "req_789" }).error
    };

    expect(event.error.category).toBe("system");
  });

  it("represents knowledge retrieval citation sources", () => {
    const event: SseEvent = {
      id: "evt_ref_1",
      type: "reference.source",
      channel: "chat",
      timestamp: "2026-07-09T00:00:00.000Z",
      reference: {
        id: "chunk_1",
        title: "runbook.md",
        sourceType: "knowledge-base",
        chunkId: "chunk_1",
        documentId: "doc_1",
        knowledgeBaseId: "kb_1",
        source: "runbook.md",
        metadata: { section: "restart" },
        score: 0.91
      }
    };

    expect(event.type).toBe("reference.source");
  });

  it("represents tool call lifecycle events", () => {
    const started: ToolCallSseEvent = {
      id: "evt_tool_1",
      type: "tool.call",
      channel: "chat",
      timestamp: "2026-07-09T00:00:00.000Z",
      toolCall: {
        id: "tool_call_1",
        name: "knowledge_retrieval",
        status: "started",
        input: { query: "restart api" }
      }
    };
    const completed: ToolCallSseEvent = {
      ...started,
      id: "evt_tool_2",
      toolCall: {
        ...started.toolCall,
        status: "completed",
        output: { results: [] }
      }
    };

    expect(started.toolCall.status).toBe("started");
    expect(completed.toolCall.status).toBe("completed");
  });
});

describe("OpenAPI contract", () => {
  it("covers required backend surfaces", () => {
      expect(Object.keys(OPENAPI_CONTRACT.paths)).toEqual(
      expect.arrayContaining([
        "/health",
        "/auth/register",
        "/auth/login",
        "/auth/logout",
        "/auth/me",
        "/chat/sessions",
        "/chat/sessions/{sessionId}",
        "/chat/sessions/{sessionId}/messages",
        "/chat/sessions/{sessionId}/messages:clear",
        "/chat/sessions/{sessionId}/messages:stream",
        "/knowledge-bases",
        "/knowledge-bases/{knowledgeBaseId}/documents",
        "/knowledge-bases/{knowledgeBaseId}/documents/{documentId}",
        "/knowledge-bases/{knowledgeBaseId}/documents/{documentId}/index-tasks",
        "/knowledge-bases/{knowledgeBaseId}/documents/{documentId}/index-tasks/{taskId}",
        "/knowledge-bases/{knowledgeBaseId}/documents/{documentId}/index-tasks/{taskId}:retry",
        "/index-tasks",
        "/index-tasks/{taskId}",
        "/aiops/diagnostics",
        "/aiops/diagnostics/{diagnosticId}",
        "/aiops/diagnostics/{diagnosticId}:stream",
        "/aiops/diagnostics/{diagnosticId}/evidence-chain"
      ])
    );
  });

  it("marks protected paths with bearer auth and unified 401/403 errors", () => {
    const protectedOperations = [
      OPENAPI_CONTRACT.paths["/chat/sessions"]?.post,
      OPENAPI_CONTRACT.paths["/chat/sessions"]?.get,
      OPENAPI_CONTRACT.paths["/chat/sessions/{sessionId}"]?.get,
      OPENAPI_CONTRACT.paths["/chat/sessions/{sessionId}"]?.delete,
      OPENAPI_CONTRACT.paths["/chat/sessions/{sessionId}/messages"]?.post,
      OPENAPI_CONTRACT.paths["/chat/sessions/{sessionId}/messages:clear"]?.post,
      OPENAPI_CONTRACT.paths["/knowledge-bases"]?.get,
      OPENAPI_CONTRACT.paths["/knowledge-bases/{knowledgeBaseId}/documents"]?.post,
      OPENAPI_CONTRACT.paths["/knowledge-bases/{knowledgeBaseId}/documents"]?.get,
      OPENAPI_CONTRACT.paths["/knowledge-bases/{knowledgeBaseId}/documents/{documentId}"]?.get,
      OPENAPI_CONTRACT.paths["/knowledge-bases/{knowledgeBaseId}/documents/{documentId}"]?.delete,
      OPENAPI_CONTRACT.paths[
        "/knowledge-bases/{knowledgeBaseId}/documents/{documentId}/index-tasks"
      ]?.post,
      OPENAPI_CONTRACT.paths[
        "/knowledge-bases/{knowledgeBaseId}/documents/{documentId}/index-tasks/{taskId}"
      ]?.get,
      OPENAPI_CONTRACT.paths[
        "/knowledge-bases/{knowledgeBaseId}/documents/{documentId}/index-tasks/{taskId}:retry"
      ]?.post,
      OPENAPI_CONTRACT.paths["/aiops/diagnostics"]?.post,
      OPENAPI_CONTRACT.paths["/aiops/diagnostics"]?.get,
      OPENAPI_CONTRACT.paths["/aiops/diagnostics/{diagnosticId}"]?.get,
      OPENAPI_CONTRACT.paths["/aiops/diagnostics/{diagnosticId}:stream"]?.post,
      OPENAPI_CONTRACT.paths["/aiops/diagnostics/{diagnosticId}/evidence-chain"]?.get,
      OPENAPI_CONTRACT.paths["/auth/logout"]?.post,
      OPENAPI_CONTRACT.paths["/auth/me"]?.get
    ];

    expect(OPENAPI_CONTRACT.components.securitySchemes.bearerAuth).toMatchObject({
      type: "http",
      scheme: "bearer"
    });
    for (const operation of protectedOperations) {
      expect(operation?.security).toEqual([{ bearerAuth: [] }]);
      expect(operation?.responses["401"].content).toBeDefined();
      expect(operation?.responses["403"].content).toBeDefined();
    }
  });

  it("describes document upload policy and document responses", () => {
    const uploadOperation = OPENAPI_CONTRACT.paths["/knowledge-bases/{knowledgeBaseId}/documents"]
      ?.post;

    expect(uploadOperation?.requestBody).toMatchObject({
      required: true
    });
    expect(JSON.stringify(uploadOperation)).toContain("multipart/form-data");
    expect(JSON.stringify(uploadOperation)).toContain("overwrite");
    expect(OPENAPI_CONTRACT.components.schemas.KnowledgeDocument).toBeDefined();
    expect(OPENAPI_CONTRACT.components.schemas.KnowledgeDocumentListApiResponse).toBeDefined();
    expect(OPENAPI_CONTRACT.components.schemas.KnowledgeDocumentDeleteApiResponse).toBeDefined();
    expect(OPENAPI_CONTRACT.components.schemas.DocumentIndexTask).toBeDefined();
    expect(OPENAPI_CONTRACT.components.schemas.DocumentIndexTaskApiResponse).toBeDefined();
    expect(OPENAPI_CONTRACT.components.schemas.KnowledgeRetrievalToolInput).toBeDefined();
    expect(OPENAPI_CONTRACT.components.schemas.KnowledgeRetrievalToolOutput).toBeDefined();
    expect(OPENAPI_CONTRACT.components.schemas.ChatMessage).toBeDefined();
    expect(OPENAPI_CONTRACT.components.schemas.ChatSessionDetailApiResponse).toBeDefined();
    expect(OPENAPI_CONTRACT.components.schemas.ChatSessionListApiResponse).toBeDefined();
    expect(OPENAPI_CONTRACT.components.schemas.AppendChatMessageRequest).toBeDefined();
    expect(OPENAPI_CONTRACT.components.schemas.StreamChatMessageRequest).toBeDefined();
    expect(OPENAPI_CONTRACT.components.schemas.ChatStreamCompleteResult).toBeDefined();
    expect(OPENAPI_CONTRACT.components.schemas.ClearChatSessionApiResponse).toBeDefined();
  });

  it("describes the protected streaming chat SSE endpoint", () => {
    const streamOperation =
      OPENAPI_CONTRACT.paths["/chat/sessions/{sessionId}/messages:stream"]?.post;

    expect(streamOperation?.security).toEqual([{ bearerAuth: [] }]);
    expect(streamOperation?.requestBody).toMatchObject({
      required: true,
      content: {
        "application/json": {
          schema: {
            $ref: "#/components/schemas/StreamChatMessageRequest"
          }
        }
      }
    });
    expect(streamOperation?.responses["200"].content).toHaveProperty("text/event-stream");
    expect(streamOperation?.responses["401"].content).toBeDefined();
    expect(streamOperation?.responses["403"].content).toBeDefined();
  });

  it("describes the protected streaming AIOps diagnostic endpoint", () => {
    const streamOperation = OPENAPI_CONTRACT.paths["/aiops/diagnostics/{diagnosticId}:stream"]?.post;

    expect(streamOperation?.security).toEqual([{ bearerAuth: [] }]);
    expect(streamOperation?.responses["200"].content).toHaveProperty("text/event-stream");
    expect(OPENAPI_CONTRACT.components.schemas.CreateAiopsDiagnosticRequest).toBeDefined();
    expect(OPENAPI_CONTRACT.components.schemas.AiopsDiagnosticReport).toBeDefined();
  });

  it("describes typed AIOps history and evidence-chain reads", () => {
    const historyOperation = OPENAPI_CONTRACT.paths["/aiops/diagnostics"]?.get;
    const evidenceChainOperation =
      OPENAPI_CONTRACT.paths["/aiops/diagnostics/{diagnosticId}/evidence-chain"]?.get;

    expect(historyOperation?.responses["200"].content).toBeDefined();
    expect(evidenceChainOperation?.responses["200"].content).toBeDefined();
    expect(OPENAPI_CONTRACT.components.schemas.AiopsDiagnosticEvidence).toBeDefined();
    expect(OPENAPI_CONTRACT.components.schemas.AiopsReportEvidenceLink).toBeDefined();
  });
});
