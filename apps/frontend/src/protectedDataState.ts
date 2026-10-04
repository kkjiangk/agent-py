import type {
  AppendChatMessageRequest,
  ChatMessage,
  ChatSessionSummary,
  CreateChatSessionRequest,
  DocumentIndexTask,
  KnowledgeBaseSummary,
  KnowledgeDocument,
  SseEvent,
  StreamChatMessageRequest,
  ToolCallAudit
} from "@agent-py/api-contracts";

import { AuthClientError } from "./authClient";
import {
  createProtectedDataClient,
  type ProtectedDataClient
} from "./protectedDataClient";
import { toUserFacingError } from "./ui/userFacingError";

export interface ProtectedDataSnapshot {
  readonly chatMessages: readonly ChatMessage[];
  readonly chatSessions: readonly ChatSessionSummary[];
  readonly errorMessage: string | null;
  readonly isLoading: boolean;
  readonly documents: readonly KnowledgeDocument[];
  readonly indexTasks: readonly DocumentIndexTask[];
  readonly knowledgeBases: readonly KnowledgeBaseSummary[];
  readonly selectedChatSessionId: string | null;
  readonly toolCallAudits: readonly ToolCallAudit[];
}

export interface CreateProtectedDataStateOptions {
  readonly client?: ProtectedDataClient;
}

export interface ProtectedDataState {
  appendChatMessage(sessionId: string, message: AppendChatMessageRequest): Promise<void>;
  clear(): void;
  clearChatSession(sessionId: string): Promise<void>;
  createChatSession(request?: CreateChatSessionRequest): Promise<ChatSessionSummary>;
  deleteDocument(document: KnowledgeDocument): Promise<void>;
  deleteChatSession(sessionId: string): Promise<void>;
  loadForCurrentUser(): Promise<void>;
  rebuildDocumentIndex(document: KnowledgeDocument): Promise<void>;
  selectChatSession(sessionId: string): Promise<void>;
  sendChatMessage(
    sessionId: string,
    request: StreamChatMessageRequest,
    onUpdate?: () => void
  ): Promise<void>;
  snapshot(): ProtectedDataSnapshot;
  uploadDocument(options: {
    file: File;
    knowledgeBaseId?: string;
    overwrite?: boolean;
  }): Promise<void>;
}

export function createProtectedDataState(
  options: CreateProtectedDataStateOptions = {}
): ProtectedDataState {
  const client = options.client ?? createProtectedDataClient();
  let chatMessages: readonly ChatMessage[] = [];
  let chatSessions: readonly ChatSessionSummary[] = [];
  let documents: readonly KnowledgeDocument[] = [];
  let indexTasks: readonly DocumentIndexTask[] = [];
  let knowledgeBases: readonly KnowledgeBaseSummary[] = [];
  let selectedChatSessionId: string | null = null;
  let toolCallAudits: readonly ToolCallAudit[] = [];
  let isLoading = false;
  let errorMessage: string | null = null;

  async function runMutation<T>(operation: () => Promise<T>): Promise<T> {
    isLoading = true;
    errorMessage = null;
    try {
      return await operation();
    } catch (error) {
      errorMessage = toUserFacingError(error);
      throw error;
    } finally {
      isLoading = false;
    }
  }

  function upsertChatSession(session: ChatSessionSummary): void {
    chatSessions = [
      session,
      ...chatSessions.filter((item) => item.id !== session.id)
    ].sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
  }

  function upsertIndexTask(task: DocumentIndexTask): void {
    indexTasks = [task, ...indexTasks.filter((item) => item.id !== task.id)];
  }

  function setDocumentIndexStatus(
    documentId: string,
    indexStatus: KnowledgeDocument["indexStatus"]
  ): void {
    documents = documents.map((document) =>
      document.id === documentId ? { ...document, indexStatus } : document
    );
  }

  function isTerminalIndexTask(task: DocumentIndexTask): boolean {
    return task.status === "succeeded" || task.status === "failed";
  }

  async function waitForDocumentIndexTask(task: DocumentIndexTask): Promise<void> {
    let currentTask = task;
    for (let attempt = 0; attempt < 10 && !isTerminalIndexTask(currentTask); attempt += 1) {
      currentTask = await client.getDocumentIndexTask({
        documentId: currentTask.documentId,
        knowledgeBaseId: currentTask.knowledgeBaseId,
        taskId: currentTask.id
      });
      upsertIndexTask(currentTask);
      if (!isTerminalIndexTask(currentTask)) {
        await new Promise((resolve) => {
          globalThis.setTimeout(resolve, 1000);
        });
      }
    }
  }

  function updateAssistantDraft(
    sessionId: string,
    content: string,
    metadata: ChatMessage["metadata"]
  ): void {
    const ownerUserId = chatSessions.find((item) => item.id === sessionId)?.ownerUserId ?? "current";
    const draft: ChatMessage = {
      id: `message_stream_${sessionId}`,
      ownerUserId,
      sessionId,
      role: "assistant",
      content,
      metadata,
      createdAt: new Date().toISOString()
    };
    const existingDraftIndex = chatMessages.findIndex((message) => message.id === draft.id);
    if (existingDraftIndex === -1) {
      chatMessages = [...chatMessages, draft];
      return;
    }
    chatMessages = chatMessages.map((message) => (message.id === draft.id ? draft : message));
  }

  function appendOptimisticUserMessage(
    sessionId: string,
    request: StreamChatMessageRequest
  ): void {
    const ownerUserId = chatSessions.find((item) => item.id === sessionId)?.ownerUserId ?? "current";
    chatMessages = [
      ...chatMessages,
      {
        id: `message_stream_user_${Date.now()}`,
        ownerUserId,
        sessionId,
        role: "user",
        content: request.content,
        metadata: request.metadata ?? {},
        createdAt: new Date().toISOString()
      }
    ];
  }

  async function loadChatSession(sessionId: string): Promise<void> {
    const [detail, audits] = await Promise.all([
      client.getChatSession(sessionId),
      client.listChatToolCallAudits?.(sessionId) ?? Promise.resolve({ items: [] })
    ]);
    selectedChatSessionId = sessionId;
    upsertChatSession(detail.session);
    chatMessages = detail.messages;
    toolCallAudits = audits.items;
  }

  function upsertLiveToolCallAudit(sessionId: string, event: Extract<SseEvent, { type: "tool.call" }>): void {
    if (event.toolCall.status === "delta") {
      return;
    }
    const existing = toolCallAudits.find((audit) => audit.id === event.toolCall.id);
    const now = new Date().toISOString();
    const completed = event.toolCall.status === "completed" || event.toolCall.status === "failed";
    const audit: ToolCallAudit = {
      id: event.toolCall.id,
      ownerUserId:
        chatSessions.find((session) => session.id === sessionId)?.ownerUserId ?? "current",
      sessionId,
      diagnosticTaskId: null,
      toolName: event.toolCall.name,
      status: event.toolCall.status,
      arguments:
        event.toolCall.input !== null && typeof event.toolCall.input === "object"
          ? event.toolCall.input as Record<string, unknown>
          : existing?.arguments ?? {},
      resultSummary:
        event.toolCall.status === "completed"
          ? JSON.stringify(event.toolCall.output ?? null)
          : existing?.resultSummary ?? null,
      errorMessage:
        event.toolCall.status === "failed"
          ? JSON.stringify(event.toolCall.output ?? null)
          : existing?.errorMessage ?? null,
      startedAt: existing?.startedAt ?? now,
      completedAt: completed ? now : null,
      durationMs: null,
      createdAt: existing?.createdAt ?? now
    };
    toolCallAudits = [audit, ...toolCallAudits.filter((item) => item.id !== audit.id)];
  }

  return {
    appendChatMessage: async (sessionId, message) => {
      await runMutation(async () => {
        const response = await client.appendChatMessage(sessionId, message);
        upsertChatSession(response.session);
        await loadChatSession(sessionId);
      });
    },
    clear: () => {
      chatMessages = [];
      chatSessions = [];
      toolCallAudits = [];
      documents = [];
      indexTasks = [];
      knowledgeBases = [];
      selectedChatSessionId = null;
      errorMessage = null;
      isLoading = false;
    },
    clearChatSession: async (sessionId) => {
      await runMutation(async () => {
        await client.clearChatSession(sessionId);
        if (selectedChatSessionId === sessionId) {
          chatMessages = [];
        }
      });
    },
    createChatSession: async (request = {}) =>
      runMutation(async () => {
        const session = await client.createChatSession(request);
        upsertChatSession(session);
        await loadChatSession(session.id);
        return chatSessions.find((item) => item.id === session.id) ?? session;
      }),
    deleteDocument: async (document) => {
      await runMutation(async () => {
        await client.deleteKnowledgeDocument({
          documentId: document.id,
          knowledgeBaseId: document.knowledgeBaseId
        });
        documents = documents.filter((item) => item.id !== document.id);
        indexTasks = indexTasks.filter((item) => item.documentId !== document.id);
      });
    },
    deleteChatSession: async (sessionId) => {
      await runMutation(async () => {
        await client.deleteChatSession(sessionId);
        chatSessions = chatSessions.filter((item) => item.id !== sessionId);
        if (selectedChatSessionId === sessionId) {
          selectedChatSessionId = null;
          chatMessages = [];
          toolCallAudits = [];
        }
      });
    },
    loadForCurrentUser: async () => {
      await runMutation(async () => {
        const response = await client.listKnowledgeBases();
        const chatResponse = await client.listChatSessions();
        knowledgeBases = response.items;
        chatSessions = chatResponse.items;
        selectedChatSessionId = null;
        chatMessages = [];
        toolCallAudits = [];
        if (knowledgeBases[0] !== undefined) {
          const documentResponse = await client.listKnowledgeDocuments(knowledgeBases[0].id);
          documents = documentResponse.items;
        } else {
          documents = [];
        }
      }).catch((error) => {
        documents = [];
        indexTasks = [];
        knowledgeBases = [];
        chatSessions = [];
        chatMessages = [];
        toolCallAudits = [];
        selectedChatSessionId = null;
        throw error;
      });
    },
    rebuildDocumentIndex: async (document) => {
      await runMutation(async () => {
        const response = await client.createDocumentIndexTask({
          documentId: document.id,
          knowledgeBaseId: document.knowledgeBaseId
        });
        indexTasks = [response.task, ...indexTasks.filter((item) => item.id !== response.task.id)];
        const documentResponse = await client.listKnowledgeDocuments(document.knowledgeBaseId);
        documents = documentResponse.items;
      });
    },
    selectChatSession: async (sessionId) => {
      await runMutation(async () => {
        await loadChatSession(sessionId);
      });
    },
    sendChatMessage: async (sessionId, request, onUpdate) => {
      await runMutation(async () => {
        selectedChatSessionId = sessionId;
        appendOptimisticUserMessage(sessionId, request);
        onUpdate?.();
        let assistantDraft = "";
        const toolCallIds: string[] = [];
        const citations: Array<NonNullable<ChatMessage["metadata"]["citations"]>[number]> = [];
        for await (const event of client.streamChatMessage(sessionId, request)) {
          if (event.type === "content.delta") {
            assistantDraft += event.delta;
            updateAssistantDraft(sessionId, assistantDraft, {
              citations,
              toolCallIds
            });
            onUpdate?.();
          }
          if (event.type === "tool.call" && !toolCallIds.includes(event.toolCall.id)) {
            toolCallIds.push(event.toolCall.id);
            updateAssistantDraft(sessionId, assistantDraft, {
              citations,
              toolCallIds
            });
            onUpdate?.();
          }
          if (event.type === "tool.call") {
            upsertLiveToolCallAudit(sessionId, event);
            onUpdate?.();
          }
          if (event.type === "reference.source") {
            citations.push(event.reference);
            updateAssistantDraft(sessionId, assistantDraft, {
              citations,
              toolCallIds
            });
            onUpdate?.();
          }
          if (event.type === "error") {
            throw new AuthClientError(event.error);
          }
        }
        await loadChatSession(sessionId);
        onUpdate?.();
      });
    },
    snapshot: () => ({
      chatMessages,
      chatSessions,
      documents,
      errorMessage,
      indexTasks,
      isLoading,
      knowledgeBases,
      selectedChatSessionId,
      toolCallAudits
    }),
    uploadDocument: async ({ file, knowledgeBaseId, overwrite = false }) => {
      const targetKnowledgeBaseId = knowledgeBaseId ?? knowledgeBases[0]?.id;
      if (targetKnowledgeBaseId === undefined) {
        errorMessage = "未找到可用的知识库。";
        throw new Error(errorMessage);
      }
      await runMutation(async () => {
        const upload = await client.uploadKnowledgeDocument({
          file,
          knowledgeBaseId: targetKnowledgeBaseId,
          overwrite
        });
        documents = [
          { ...upload.document, indexStatus: "indexing" },
          ...documents.filter((item) => item.id !== upload.document.id)
        ];
        const taskResponse = await client.createDocumentIndexTask({
          documentId: upload.document.id,
          knowledgeBaseId: upload.document.knowledgeBaseId
        });
        upsertIndexTask(taskResponse.task);
        setDocumentIndexStatus(upload.document.id, "indexing");
        await waitForDocumentIndexTask(taskResponse.task);
        const documentResponse = await client.listKnowledgeDocuments(targetKnowledgeBaseId);
        documents = documentResponse.items;
      });
    }
  };
}
