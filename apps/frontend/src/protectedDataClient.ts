import type {
  ApiResponse,
  AppendChatMessageRequest,
  ChatSessionDetailResponse,
  ChatSessionListResponse,
  ChatSessionMutationResponse,
  ChatSessionSummary,
  ClearChatSessionResponse,
  CreateChatSessionRequest,
  CreateDocumentIndexTaskResponse,
  DeleteChatSessionResponse,
  DocumentIndexTask,
  KnowledgeBaseListResponse,
  KnowledgeDocument,
  KnowledgeDocumentDeleteResponse,
  KnowledgeDocumentListResponse,
  KnowledgeDocumentUploadResponse,
  RetryDocumentIndexTaskResponse,
  SseEvent,
  StreamChatMessageRequest,
  ChatToolCallAuditListResponse
} from "@agent-py/api-contracts";

import { AUTH_TOKEN_STORAGE_KEY, AuthClientError, parseApiError } from "./authClient";
import { API_BASE_URL } from "./config";

export interface ProtectedDataClient {
  appendChatMessage(
    sessionId: string,
    message: AppendChatMessageRequest
  ): Promise<ChatSessionMutationResponse>;
  clearChatSession(sessionId: string): Promise<ClearChatSessionResponse>;
  createChatSession(request: CreateChatSessionRequest): Promise<ChatSessionSummary>;
  deleteChatSession(sessionId: string): Promise<DeleteChatSessionResponse>;
  createDocumentIndexTask(options: {
    documentId: string;
    knowledgeBaseId: string;
  }): Promise<CreateDocumentIndexTaskResponse>;
  deleteKnowledgeDocument(options: {
    documentId: string;
    knowledgeBaseId: string;
  }): Promise<KnowledgeDocumentDeleteResponse>;
  getDocumentIndexTask(options: {
    documentId: string;
    knowledgeBaseId: string;
    taskId: string;
  }): Promise<DocumentIndexTask>;
  getChatSession(sessionId: string): Promise<ChatSessionDetailResponse>;
  getKnowledgeDocument(options: {
    documentId: string;
    knowledgeBaseId: string;
  }): Promise<KnowledgeDocument>;
  listChatSessions(): Promise<ChatSessionListResponse>;
  listChatToolCallAudits?(sessionId: string): Promise<ChatToolCallAuditListResponse>;
  listKnowledgeBases(): Promise<KnowledgeBaseListResponse>;
  listKnowledgeDocuments(knowledgeBaseId: string): Promise<KnowledgeDocumentListResponse>;
  streamChatMessage(
    sessionId: string,
    request: StreamChatMessageRequest
  ): AsyncIterable<SseEvent>;
  retryDocumentIndexTask(options: {
    documentId: string;
    knowledgeBaseId: string;
    taskId: string;
  }): Promise<RetryDocumentIndexTaskResponse>;
  uploadKnowledgeDocument(options: {
    file: File;
    knowledgeBaseId: string;
    overwrite?: boolean;
  }): Promise<KnowledgeDocumentUploadResponse>;
}

export interface CreateProtectedDataClientOptions {
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof fetch;
  readonly storage?: Storage;
}

export function createProtectedDataClient(
  options: CreateProtectedDataClientOptions = {}
): ProtectedDataClient {
  const baseUrl = options.baseUrl ?? API_BASE_URL;
  const fetchImpl = options.fetchImpl ?? fetch;
  const storage = options.storage ?? window.localStorage;

  async function request<TData>(
    path: string,
    init: RequestInit & { readonly isMultipart?: boolean } = {}
  ): Promise<TData> {
    const { isMultipart, ...fetchInit } = init;
    const headers = new Headers();
    headers.set("Accept", "application/json");
    if (fetchInit.body !== undefined && isMultipart !== true) {
      headers.set("Content-Type", "application/json");
    }
    const token = storage.getItem(AUTH_TOKEN_STORAGE_KEY);
    if (token !== null) {
      headers.set("Authorization", `Bearer ${token}`);
    }

    const response = await fetchImpl(`${baseUrl}${path}`, {
      ...fetchInit,
      headers
    });
    if (!response.ok) {
      throw new AuthClientError(await parseApiError(response));
    }

    const payload = (await response.json()) as ApiResponse<TData>;
    if (!payload.ok) {
      throw new AuthClientError(payload.error);
    }
    return payload.data;
  }

  async function* streamRequest<TEvent>(
    path: string,
    init: RequestInit = {}
  ): AsyncIterable<TEvent> {
    const headers = new Headers();
    headers.set("Accept", "text/event-stream");
    if (init.body !== undefined) {
      headers.set("Content-Type", "application/json");
    }
    const token = storage.getItem(AUTH_TOKEN_STORAGE_KEY);
    if (token !== null) {
      headers.set("Authorization", `Bearer ${token}`);
    }

    const response = await fetchImpl(`${baseUrl}${path}`, {
      ...init,
      headers
    });
    if (!response.ok) {
      throw new AuthClientError(await parseApiError(response));
    }
    if (response.body === null) {
      throw new AuthClientError({
        code: "SYSTEM_UNAVAILABLE",
        category: "system",
        httpStatus: 503,
        message: "服务暂时不可用，请稍后重试。"
      });
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const parsed = _parseSseFrames<TEvent>(buffer);
      buffer = parsed.remainder;
      for (const event of parsed.events) {
        yield event;
      }
    }
    buffer += decoder.decode();
    const parsed = _parseSseFrames<TEvent>(buffer);
    for (const event of parsed.events) {
      yield event;
    }
  }

  return {
    appendChatMessage: (sessionId, message) =>
      request<ChatSessionMutationResponse>(`/chat/sessions/${sessionId}/messages`, {
        body: JSON.stringify(message),
        method: "POST"
      }),
    clearChatSession: (sessionId) =>
      request<ClearChatSessionResponse>(`/chat/sessions/${sessionId}/messages:clear`, {
        method: "POST"
      }),
    createChatSession: (body) =>
      request<ChatSessionSummary>("/chat/sessions", {
        body: JSON.stringify(body),
        method: "POST"
      }),
    deleteChatSession: (sessionId) =>
      request<DeleteChatSessionResponse>(`/chat/sessions/${sessionId}`, { method: "DELETE" }),
    createDocumentIndexTask: ({ documentId, knowledgeBaseId }) =>
      request<CreateDocumentIndexTaskResponse>(
        `/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/index-tasks`,
        { method: "POST" }
      ),
    deleteKnowledgeDocument: ({ documentId, knowledgeBaseId }) =>
      request<KnowledgeDocumentDeleteResponse>(
        `/knowledge-bases/${knowledgeBaseId}/documents/${documentId}`,
        { method: "DELETE" }
      ),
    getDocumentIndexTask: ({ documentId, knowledgeBaseId, taskId }) =>
      request<DocumentIndexTask>(
        `/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/index-tasks/${taskId}`
      ),
    getChatSession: (sessionId) =>
      request<ChatSessionDetailResponse>(`/chat/sessions/${sessionId}`),
    getKnowledgeDocument: ({ documentId, knowledgeBaseId }) =>
      request<KnowledgeDocument>(`/knowledge-bases/${knowledgeBaseId}/documents/${documentId}`),
    listChatSessions: () => request<ChatSessionListResponse>("/chat/sessions"),
    listChatToolCallAudits: (sessionId) =>
      request<ChatToolCallAuditListResponse>(`/chat/sessions/${sessionId}/tool-call-audits`),
    listKnowledgeBases: () => request<KnowledgeBaseListResponse>("/knowledge-bases"),
    listKnowledgeDocuments: (knowledgeBaseId) =>
      request<KnowledgeDocumentListResponse>(`/knowledge-bases/${knowledgeBaseId}/documents`),
    streamChatMessage: (sessionId, body) =>
      streamRequest<SseEvent>(`/chat/sessions/${sessionId}/messages:stream`, {
        body: JSON.stringify(body),
        method: "POST"
      }),
    retryDocumentIndexTask: ({ documentId, knowledgeBaseId, taskId }) =>
      request<RetryDocumentIndexTaskResponse>(
        `/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/index-tasks/${taskId}:retry`,
        { method: "POST" }
      ),
    uploadKnowledgeDocument: ({ file, knowledgeBaseId, overwrite = false }) => {
      const form = new FormData();
      form.set("file", file);
      form.set("overwrite", String(overwrite));
      return request<KnowledgeDocumentUploadResponse>(
        `/knowledge-bases/${knowledgeBaseId}/documents`,
        {
          body: form,
          isMultipart: true,
          method: "POST"
        }
      );
    }
  };
}

function _parseSseFrames<TEvent>(buffer: string): {
  readonly events: TEvent[];
  readonly remainder: string;
} {
  const events: TEvent[] = [];
  const chunks = buffer.split("\n\n");
  const remainder = chunks.pop() ?? "";
  for (const chunk of chunks) {
    const dataLines = chunk
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice("data:".length).trimStart());
    if (dataLines.length === 0) {
      continue;
    }
    events.push(JSON.parse(dataLines.join("\n")) as TEvent);
  }
  return { events, remainder };
}
