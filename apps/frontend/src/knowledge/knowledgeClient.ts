import type {
  CreateDocumentIndexTaskResponse,
  DocumentChunkingConfiguration,
  DocumentChunkPreview,
  DocumentIndexTask,
  KnowledgeBaseListResponse,
  KnowledgeDocument,
  KnowledgeDocumentDeleteResponse,
  KnowledgeDocumentListResponse,
  KnowledgeDocumentUploadResponse,
  RetryDocumentIndexTaskResponse
} from "@agent-py/api-contracts";

import { AUTH_TOKEN_STORAGE_KEY } from "../authClient";
import { createApiClient } from "../api/apiClient";
import { API_BASE_URL } from "../config";

export interface KnowledgeClient {
  createIndexTask(options: { documentId: string; knowledgeBaseId: string }): Promise<CreateDocumentIndexTaskResponse>;
  deleteDocument(options: { documentId: string; knowledgeBaseId: string }): Promise<KnowledgeDocumentDeleteResponse>;
  getDocument(options: { documentId: string; knowledgeBaseId: string }): Promise<KnowledgeDocument>;
  getChunkPreview?(options: { documentId: string; knowledgeBaseId: string }): Promise<DocumentChunkPreview>;
  getIndexTask(options: { documentId: string; knowledgeBaseId: string; taskId: string }): Promise<DocumentIndexTask>;
  listKnowledgeBases(): Promise<KnowledgeBaseListResponse>;
  listKnowledgeDocuments(knowledgeBaseId: string): Promise<KnowledgeDocumentListResponse>;
  retryIndexTask(options: { documentId: string; knowledgeBaseId: string; taskId: string }): Promise<RetryDocumentIndexTaskResponse>;
  uploadDocument(options: { file: File; knowledgeBaseId: string; overwrite: boolean; chunking?: DocumentChunkingConfiguration }): Promise<KnowledgeDocumentUploadResponse>;
}

export interface CreateKnowledgeClientOptions {
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof fetch;
  readonly getAccessToken?: () => string | null;
}

export function createKnowledgeClient(options: CreateKnowledgeClientOptions = {}): KnowledgeClient {
  const getAccessToken = options.getAccessToken ?? (() => window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY));
  const api = createApiClient({
    baseUrl: options.baseUrl ?? API_BASE_URL,
    ...(options.fetchImpl === undefined ? {} : { fetchImpl: options.fetchImpl }),
    getAccessToken
  });

  return {
    createIndexTask: ({ documentId, knowledgeBaseId }) =>
      api.request<CreateDocumentIndexTaskResponse>(
        `/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/index-tasks`,
        { method: "POST" }
      ),
    deleteDocument: ({ documentId, knowledgeBaseId }) =>
      api.request<KnowledgeDocumentDeleteResponse>(
        `/knowledge-bases/${knowledgeBaseId}/documents/${documentId}`,
        { method: "DELETE" }
      ),
    getDocument: ({ documentId, knowledgeBaseId }) =>
      api.request<KnowledgeDocument>(`/knowledge-bases/${knowledgeBaseId}/documents/${documentId}`),
    getChunkPreview: ({ documentId, knowledgeBaseId }) => api.request<{ preview: DocumentChunkPreview }>(`/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/chunk-preview`).then((result) => result.preview),
    getIndexTask: ({ documentId, knowledgeBaseId, taskId }) =>
      api.request<DocumentIndexTask>(
        `/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/index-tasks/${taskId}`
      ),
    listKnowledgeBases: () => api.request<KnowledgeBaseListResponse>("/knowledge-bases"),
    listKnowledgeDocuments: (knowledgeBaseId) =>
      api.request<KnowledgeDocumentListResponse>(`/knowledge-bases/${knowledgeBaseId}/documents`),
    retryIndexTask: ({ documentId, knowledgeBaseId, taskId }) =>
      api.request<RetryDocumentIndexTaskResponse>(
        `/knowledge-bases/${knowledgeBaseId}/documents/${documentId}/index-tasks/${taskId}:retry`,
        { method: "POST" }
      ),
    uploadDocument: ({ file, knowledgeBaseId, overwrite, chunking }) => {
      const form = new FormData();
      form.set("file", file);
      form.set("overwrite", String(overwrite));
      if (chunking !== undefined) {
        form.set("chunking", JSON.stringify(chunking));
      }
      return api.request<KnowledgeDocumentUploadResponse>(`/knowledge-bases/${knowledgeBaseId}/documents`, {
        body: form,
        method: "POST"
      });
    }
  };
}
