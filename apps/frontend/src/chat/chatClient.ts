import type {
  ChatSessionDetailResponse,
  ChatSessionListResponse,
  ChatSessionSummary,
  ChatToolCallAuditListResponse,
  ChatAssemblyConfigurationResponse,
  ChatPromptResponse,
  ChatSkillUploadResponse,
  ChatMemoryMode,
  CreateChatSessionRequest,
  CreateChatPromptRequest,
  DeleteChatPromptResponse,
  DeleteChatSkillResponse,
  DeleteChatSessionResponse,
  SseEvent,
  StreamChatMessageRequest,
  UpdateChatAssemblyConfigurationRequest,
  UpdateChatPromptRequest
} from "@agent-py/api-contracts";

import { API_BASE_URL } from "../config";
import { AUTH_TOKEN_STORAGE_KEY } from "../authClient";
import { createApiClient } from "../api/apiClient";
import { createSseClient } from "../api/sseClient";

export interface ChatClient {
  createSession(request?: CreateChatSessionRequest): Promise<ChatSessionSummary>;
  deleteSession(sessionId: string): Promise<DeleteChatSessionResponse>;
  getSession(sessionId: string): Promise<ChatSessionDetailResponse>;
  listSessions(): Promise<ChatSessionListResponse>;
  listToolCallAudits(sessionId: string): Promise<ChatToolCallAuditListResponse>;
  updateMemoryMode(sessionId: string, mode: ChatMemoryMode): Promise<ChatSessionSummary>;
  compactMemory(sessionId: string): Promise<ChatSessionSummary>;
  getConfiguration?(): Promise<ChatAssemblyConfigurationResponse>;
  updateConfiguration?(request: UpdateChatAssemblyConfigurationRequest): Promise<ChatAssemblyConfigurationResponse>;
  createPrompt?(request: CreateChatPromptRequest): Promise<ChatPromptResponse>;
  updatePrompt?(promptId: string, request: UpdateChatPromptRequest): Promise<ChatPromptResponse>;
  deletePrompt?(promptId: string): Promise<DeleteChatPromptResponse>;
  uploadSkill?(file: File): Promise<ChatSkillUploadResponse>;
  deleteSkill?(skillId: string): Promise<DeleteChatSkillResponse>;
  streamMessage(sessionId: string, request: StreamChatMessageRequest): AsyncIterable<SseEvent>;
}

export interface CreateChatClientOptions {
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof fetch;
  readonly getAccessToken?: () => string | null;
}

export function createChatClient(options: CreateChatClientOptions = {}): ChatClient {
  const getAccessToken =
    options.getAccessToken ?? (() => window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY));
  const transportOptions = {
    baseUrl: options.baseUrl ?? API_BASE_URL,
    ...(options.fetchImpl === undefined ? {} : { fetchImpl: options.fetchImpl }),
    getAccessToken
  };
  const api = createApiClient(transportOptions);
  const sse = createSseClient(transportOptions);

  return {
    createSession: (request = {}) =>
      api.request<ChatSessionSummary>("/chat/sessions", {
        body: JSON.stringify(request),
        method: "POST"
      }),
    deleteSession: (sessionId) =>
      api.request<DeleteChatSessionResponse>(`/chat/sessions/${sessionId}`, { method: "DELETE" }),
    getSession: (sessionId) =>
      api.request<ChatSessionDetailResponse>(`/chat/sessions/${sessionId}`),
    listSessions: () => api.request<ChatSessionListResponse>("/chat/sessions"),
    listToolCallAudits: (sessionId) =>
      api.request<ChatToolCallAuditListResponse>(`/chat/sessions/${sessionId}/tool-call-audits`),
    updateMemoryMode: (sessionId, mode) =>
      api.request<ChatSessionSummary>(`/chat/sessions/${sessionId}/memory`, {
        body: JSON.stringify({ mode }),
        method: "PUT"
      }),
    compactMemory: (sessionId) =>
      api.request<ChatSessionSummary>(`/chat/sessions/${sessionId}/memory:compact`, {
        method: "POST"
      }),
    getConfiguration: () => api.request<ChatAssemblyConfigurationResponse>("/chat/configuration"),
    updateConfiguration: (body) => api.request<ChatAssemblyConfigurationResponse>("/chat/configuration", { body: JSON.stringify(body), method: "PUT" }),
    createPrompt: (body) =>
      api.request<ChatPromptResponse>("/chat/prompts", {
        body: JSON.stringify(body),
        method: "POST"
      }),
    updatePrompt: (promptId, body) =>
      api.request<ChatPromptResponse>(`/chat/prompts/${promptId}`, {
        body: JSON.stringify(body),
        method: "PUT"
      }),
    deletePrompt: (promptId) =>
      api.request<DeleteChatPromptResponse>(`/chat/prompts/${promptId}`, { method: "DELETE" }),
    uploadSkill: (file) => {
      const formData = new FormData();
      formData.append("file", file);
      return api.request<ChatSkillUploadResponse>("/chat/skills", {
        body: formData,
        method: "POST"
      });
    },
    deleteSkill: (skillId) =>
      api.request<DeleteChatSkillResponse>(`/chat/skills/${skillId}`, { method: "DELETE" }),
    streamMessage: (sessionId, request) =>
      sse.stream(`/chat/sessions/${sessionId}/messages:stream`, {
        body: JSON.stringify(request),
        method: "POST"
      })
  };
}
