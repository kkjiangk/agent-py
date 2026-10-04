import { describe, expect, it } from "vitest";

import type {
  ChatMessage,
  ChatSessionSummary,
  DocumentIndexTask,
  KnowledgeDocument,
  SseEvent
} from "@agent-py/api-contracts";

import { createProtectedDataClient } from "../src/protectedDataClient";
import { createProtectedDataState } from "../src/protectedDataState";

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  clear(): void {
    this.values.clear();
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  key(index: number): string | null {
    return Array.from(this.values.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

describe("protected data client", () => {
  it("loads protected resources with the stored bearer token", async () => {
    const storage = new MemoryStorage();
    const requests: Array<{ input: RequestInfo | URL; init: RequestInit }> = [];
    storage.setItem("super-ai.auth-token", "token-1");
    const client = createProtectedDataClient({
      storage,
      fetchImpl: async (input, init) => {
        requests.push({ input, init: init ?? {} });
        return new Response(
          JSON.stringify({
            ok: true,
            data: { items: [{ id: "kb_1", name: "User KB", ownerUserId: "user_1" }] },
            meta: { requestId: "req_1" }
          }),
          { status: 200, headers: { "content-type": "application/json" } }
        );
      }
    });

    const data = await client.listKnowledgeBases();

    expect(data.items).toEqual([{ id: "kb_1", name: "User KB", ownerUserId: "user_1" }]);
    expect(new Headers(requests[0]?.init.headers).get("Authorization")).toBe("Bearer token-1");
  });

  it("uploads and deletes documents with authenticated requests", async () => {
    const storage = new MemoryStorage();
    const requests: Array<{ input: RequestInfo | URL; init: RequestInit }> = [];
    storage.setItem("super-ai.auth-token", "token-1");
    const client = createProtectedDataClient({
      storage,
      fetchImpl: async (input, init) => {
        requests.push({ input, init: init ?? {} });
        return new Response(
          JSON.stringify({
            ok: true,
            data:
              init?.method === "DELETE"
                ? { deleted: true, documentId: "doc_1" }
                : {
                    document: {
                      id: "doc_1",
                      knowledgeBaseId: "kb_1",
                      ownerUserId: "user_1",
                      filename: "runbook.md",
                      sizeBytes: 7,
                      mimeType: "text/markdown",
                      contentHash: "sha256:abc",
                      status: "ready",
                      indexStatus: "pending",
                      uploadedAt: "2026-07-09T00:00:00.000Z",
                      updatedAt: "2026-07-09T00:00:00.000Z"
                    },
                    duplicateOfDocumentId: null,
                    overwrite: false
                  },
            meta: { requestId: "req_1" }
          }),
          { status: 200, headers: { "content-type": "application/json" } }
        );
      }
    });

    const upload = await client.uploadKnowledgeDocument({
      knowledgeBaseId: "kb_1",
      file: new File(["runbook"], "runbook.md", { type: "text/markdown" }),
      overwrite: false
    });
    const deletion = await client.deleteKnowledgeDocument({
      knowledgeBaseId: "kb_1",
      documentId: "doc_1"
    });

    expect(upload.document.filename).toBe("runbook.md");
    expect(deletion.deleted).toBe(true);
    expect(requests[0]?.input.toString()).toContain("/knowledge-bases/kb_1/documents");
    expect(requests[0]?.init.method).toBe("POST");
    expect(requests[0]?.init.body).toBeInstanceOf(FormData);
    expect(requests[1]?.input.toString()).toContain(
      "/knowledge-bases/kb_1/documents/doc_1"
    );
    expect(requests[1]?.init.method).toBe("DELETE");
    expect(new Headers(requests[1]?.init.headers).get("Authorization")).toBe("Bearer token-1");
  });

  it("creates and retries document index tasks with authenticated requests", async () => {
    const storage = new MemoryStorage();
    const requests: Array<{ input: RequestInfo | URL; init: RequestInit }> = [];
    storage.setItem("super-ai.auth-token", "token-1");
    const client = createProtectedDataClient({
      storage,
      fetchImpl: async (input, init) => {
        requests.push({ input, init: init ?? {} });
        return new Response(
          JSON.stringify({
            ok: true,
            data: input.toString().endsWith(":retry")
              ? {
                  task: _indexTask({ id: "index_task_2", retryOfTaskId: "index_task_1" }),
                  retriedFromTaskId: "index_task_1",
                  scheduled: true
                }
              : input.toString().includes("index-tasks/index_task_1")
                ? _indexTask({ id: "index_task_1" })
                : { task: _indexTask({ id: "index_task_1" }), scheduled: true },
            meta: { requestId: "req_1" }
          }),
          { status: 200, headers: { "content-type": "application/json" } }
        );
      }
    });

    const created = await client.createDocumentIndexTask({
      knowledgeBaseId: "kb_1",
      documentId: "doc_1"
    });
    const read = await client.getDocumentIndexTask({
      knowledgeBaseId: "kb_1",
      documentId: "doc_1",
      taskId: "index_task_1"
    });
    const retried = await client.retryDocumentIndexTask({
      knowledgeBaseId: "kb_1",
      documentId: "doc_1",
      taskId: "index_task_1"
    });

    expect(created.scheduled).toBe(true);
    expect(read.id).toBe("index_task_1");
    expect(retried.retriedFromTaskId).toBe("index_task_1");
    expect(requests.map((request) => request.init.method)).toEqual(["POST", undefined, "POST"]);
    expect(new Headers(requests[2]?.init.headers).get("Authorization")).toBe("Bearer token-1");
  });

  it("manages chat sessions with authenticated API requests", async () => {
    const storage = new MemoryStorage();
    const requests: Array<{ input: RequestInfo | URL; init: RequestInit }> = [];
    storage.setItem("super-ai.auth-token", "token-1");
    const client = createProtectedDataClient({
      storage,
      fetchImpl: async (input, init) => {
        requests.push({ input, init: init ?? {} });
        const url = input.toString();
        const responseData = url.endsWith("/chat/sessions")
          ? init?.method === "POST"
            ? _chatSession()
            : { items: [_chatSession()] }
          : url.endsWith("/messages")
            ? { session: _chatSession({ title: "Restart API" }), message: _chatMessage() }
            : url.endsWith("/messages:clear")
              ? { sessionId: "chat_1", cleared: true, deletedMessages: 1 }
              : init?.method === "DELETE"
                ? { sessionId: "chat_1", deleted: true }
                : { session: _chatSession(), messages: [_chatMessage()] };
        return new Response(
          JSON.stringify({
            ok: true,
            data: responseData,
            meta: { requestId: "req_1" }
          }),
          { status: 200, headers: { "content-type": "application/json" } }
        );
      }
    });

    const created = await client.createChatSession({ title: "Restart API" });
    const listed = await client.listChatSessions();
    const detail = await client.getChatSession("chat_1");
    const appended = await client.appendChatMessage("chat_1", {
      role: "user",
      content: "How do I restart the API?"
    });
    const cleared = await client.clearChatSession("chat_1");
    const deleted = await client.deleteChatSession("chat_1");

    expect(created.id).toBe("chat_1");
    expect(listed.items[0]?.id).toBe("chat_1");
    expect(detail.messages[0]?.metadata.toolCallIds).toEqual(["tool_call_1"]);
    expect(appended.message?.role).toBe("user");
    expect(cleared.deletedMessages).toBe(1);
    expect(deleted.deleted).toBe(true);
    expect(requests.map((request) => request.input.toString())).toEqual([
      "http://127.0.0.1:8000/chat/sessions",
      "http://127.0.0.1:8000/chat/sessions",
      "http://127.0.0.1:8000/chat/sessions/chat_1",
      "http://127.0.0.1:8000/chat/sessions/chat_1/messages",
      "http://127.0.0.1:8000/chat/sessions/chat_1/messages:clear",
      "http://127.0.0.1:8000/chat/sessions/chat_1"
    ]);
    expect(new Headers(requests[0]?.init.headers).get("Authorization")).toBe("Bearer token-1");
  });

  it("streams chat messages with authenticated SSE parsing", async () => {
    const storage = new MemoryStorage();
    const requests: Array<{ input: RequestInfo | URL; init: RequestInit }> = [];
    storage.setItem("super-ai.auth-token", "token-1");
    const client = createProtectedDataClient({
      storage,
      fetchImpl: async (input, init) => {
        requests.push({ input, init: init ?? {} });
        return new Response(
          _sseStream([
            {
              event: "tool.call",
              data: {
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
              }
            },
            {
              event: "content.delta",
              data: {
                id: "evt_delta_1",
                type: "content.delta",
                channel: "chat",
                timestamp: "2026-07-09T00:00:00.000Z",
                delta: "Use the runbook.",
                sequence: 1
              }
            },
            {
              event: "complete",
              data: {
                id: "evt_complete_1",
                type: "complete",
                channel: "chat",
                timestamp: "2026-07-09T00:00:01.000Z",
                result: {
                  session: _chatSession(),
                  message: _chatMessage({
                    role: "assistant",
                    content: "Use the runbook.",
                    metadata: { toolCallIds: ["tool_call_1"] }
                  })
                }
              }
            }
          ]),
          { status: 200, headers: { "content-type": "text/event-stream" } }
        );
      }
    });

    const events: SseEvent[] = [];
    for await (const event of client.streamChatMessage("chat_1", {
      content: "How do I restart the API?"
    })) {
      events.push(event);
    }

    expect(requests[0]?.input.toString()).toBe(
      "http://127.0.0.1:8000/chat/sessions/chat_1/messages:stream"
    );
    expect(requests[0]?.init.method).toBe("POST");
    expect(new Headers(requests[0]?.init.headers).get("Authorization")).toBe("Bearer token-1");
    expect(JSON.parse(requests[0]?.init.body?.toString() ?? "{}")).toEqual({
      content: "How do I restart the API?"
    });
    expect(events.map((event) => event.type)).toEqual(["tool.call", "content.delta", "complete"]);
  });
});

describe("protected data state", () => {
  it("loads scoped data for the current user and clears it on logout", async () => {
    const state = createProtectedDataState({
      client: {
        listKnowledgeBases: async () => ({
          items: [{ id: "kb_1", name: "User KB", ownerUserId: "user_1" }]
        }),
        getKnowledgeDocument: async () => ({
          id: "doc_1",
          knowledgeBaseId: "kb_1",
          ownerUserId: "user_1",
          filename: "runbook.md",
          sizeBytes: 7,
          mimeType: "text/markdown",
          contentHash: "sha256:abc",
          status: "ready",
          indexStatus: "pending",
          uploadedAt: "2026-07-09T00:00:00.000Z",
          updatedAt: "2026-07-09T00:00:00.000Z"
        }),
        listKnowledgeDocuments: async () => ({
          items: [
            {
              id: "doc_1",
              knowledgeBaseId: "kb_1",
              ownerUserId: "user_1",
              filename: "runbook.md",
              sizeBytes: 7,
              mimeType: "text/markdown",
              contentHash: "sha256:abc",
              status: "ready",
              indexStatus: "pending",
              uploadedAt: "2026-07-09T00:00:00.000Z",
              updatedAt: "2026-07-09T00:00:00.000Z"
            }
          ]
        }),
        uploadKnowledgeDocument: async () => ({
          document: {
            id: "doc_2",
            knowledgeBaseId: "kb_1",
            ownerUserId: "user_1",
            filename: "new.md",
            sizeBytes: 3,
            mimeType: "text/markdown",
            contentHash: "sha256:def",
            status: "ready",
            indexStatus: "pending",
            uploadedAt: "2026-07-09T00:00:00.000Z",
            updatedAt: "2026-07-09T00:00:00.000Z"
          },
          duplicateOfDocumentId: null,
          overwrite: false
        }),
        createDocumentIndexTask: async () => ({
          task: _indexTask({ id: "index_task_1" }),
          scheduled: true
        }),
        getDocumentIndexTask: async () => _indexTask({ id: "index_task_1" }),
        retryDocumentIndexTask: async () => ({
          task: _indexTask({ id: "index_task_2", retryOfTaskId: "index_task_1" }),
          retriedFromTaskId: "index_task_1",
          scheduled: true
        }),
        deleteKnowledgeDocument: async () => ({ deleted: true, documentId: "doc_1" }),
        listChatSessions: async () => ({ items: [] }),
        getChatSession: async () => ({ session: _chatSession(), messages: [] }),
        createChatSession: async () => _chatSession(),
        appendChatMessage: async () => ({ session: _chatSession(), message: _chatMessage() }),
        streamChatMessage: _emptyChatStream,
        clearChatSession: async () => ({
          sessionId: "chat_1",
          cleared: true,
          deletedMessages: 0
        }),
        deleteChatSession: async () => ({ sessionId: "chat_1", deleted: true })
      }
    });

    await state.loadForCurrentUser();

    expect(state.snapshot().documents).toHaveLength(1);

    state.clear();

    expect(state.snapshot().knowledgeBases).toEqual([]);
    expect(state.snapshot().documents).toEqual([]);
    expect(state.snapshot().isLoading).toBe(false);
  });

  it("rebuilds a document index and refreshes document status", async () => {
    const state = createProtectedDataState({
      client: {
        listKnowledgeBases: async () => ({
          items: [{ id: "kb_1", name: "User KB", ownerUserId: "user_1" }]
        }),
        getKnowledgeDocument: async () => _document({ indexStatus: "indexed" }),
        listKnowledgeDocuments: async () => ({
          items: [_document({ indexStatus: "indexed" })]
        }),
        uploadKnowledgeDocument: async () => ({
          document: _document({ indexStatus: "pending" }),
          duplicateOfDocumentId: null,
          overwrite: false
        }),
        createDocumentIndexTask: async () => ({
          task: _indexTask({ id: "index_task_1" }),
          scheduled: true
        }),
        getDocumentIndexTask: async () => _indexTask({ id: "index_task_1" }),
        retryDocumentIndexTask: async () => ({
          task: _indexTask({ id: "index_task_2", retryOfTaskId: "index_task_1" }),
          retriedFromTaskId: "index_task_1",
          scheduled: true
        }),
        deleteKnowledgeDocument: async () => ({ deleted: true, documentId: "doc_1" }),
        listChatSessions: async () => ({ items: [] }),
        getChatSession: async () => ({ session: _chatSession(), messages: [] }),
        createChatSession: async () => _chatSession(),
        appendChatMessage: async () => ({ session: _chatSession(), message: _chatMessage() }),
        streamChatMessage: _emptyChatStream,
        clearChatSession: async () => ({
          sessionId: "chat_1",
          cleared: true,
          deletedMessages: 0
        }),
        deleteChatSession: async () => ({ sessionId: "chat_1", deleted: true })
      }
    });

    await state.loadForCurrentUser();
    await state.rebuildDocumentIndex(_document({ indexStatus: "pending" }));

    expect(state.snapshot().documents[0]?.indexStatus).toBe("indexed");
    expect(state.snapshot().indexTasks[0]?.id).toBe("index_task_1");
  });

  it("starts indexing automatically after document upload", async () => {
    const calls: string[] = [];
    let listedDocuments: readonly KnowledgeDocument[] = [];
    const state = createProtectedDataState({
      client: {
        listKnowledgeBases: async () => ({
          items: [{ id: "kb_1", name: "User KB", ownerUserId: "user_1" }]
        }),
        getKnowledgeDocument: async () => _document({ id: "doc_2", indexStatus: "indexed" }),
        listKnowledgeDocuments: async () => ({ items: listedDocuments }),
        uploadKnowledgeDocument: async () => {
          calls.push("upload");
          const document = _document({ id: "doc_2", indexStatus: "pending" });
          listedDocuments = [document];
          return {
            document,
            duplicateOfDocumentId: null,
            overwrite: false
          };
        },
        createDocumentIndexTask: async ({ documentId }) => {
          calls.push(`createIndex:${documentId}`);
          return {
            task: _indexTask({
              id: "index_task_2",
              documentId,
              status: "running"
            }),
            scheduled: true
          };
        },
        getDocumentIndexTask: async ({ documentId, taskId }) => {
          calls.push(`poll:${taskId}`);
          listedDocuments = [_document({ id: documentId, indexStatus: "indexed" })];
          return _indexTask({
            id: taskId,
            documentId,
            status: "succeeded"
          });
        },
        retryDocumentIndexTask: async () => ({
          task: _indexTask({ id: "index_task_3", retryOfTaskId: "index_task_2" }),
          retriedFromTaskId: "index_task_2",
          scheduled: true
        }),
        deleteKnowledgeDocument: async () => ({ deleted: true, documentId: "doc_2" }),
        listChatSessions: async () => ({ items: [] }),
        getChatSession: async () => ({ session: _chatSession(), messages: [] }),
        createChatSession: async () => _chatSession(),
        appendChatMessage: async () => ({ session: _chatSession(), message: _chatMessage() }),
        streamChatMessage: _emptyChatStream,
        clearChatSession: async () => ({
          sessionId: "chat_1",
          cleared: true,
          deletedMessages: 0
        }),
        deleteChatSession: async () => ({ sessionId: "chat_1", deleted: true })
      }
    });

    await state.loadForCurrentUser();
    await state.uploadDocument({
      file: new File(["runbook"], "runbook.md", { type: "text/markdown" })
    });

    expect(calls).toEqual(["upload", "createIndex:doc_2", "poll:index_task_2"]);
    expect(state.snapshot().documents[0]?.indexStatus).toBe("indexed");
    expect(state.snapshot().indexTasks[0]?.status).toBe("succeeded");
  });

  it("loads, selects, mutates, and clears chat state through the API client", async () => {
    const calls: string[] = [];
    const state = createProtectedDataState({
      client: {
        listKnowledgeBases: async () => ({
          items: [{ id: "kb_1", name: "User KB", ownerUserId: "user_1" }]
        }),
        listKnowledgeDocuments: async () => ({ items: [] }),
        getKnowledgeDocument: async () => _document(),
        uploadKnowledgeDocument: async () => ({
          document: _document(),
          duplicateOfDocumentId: null,
          overwrite: false
        }),
        createDocumentIndexTask: async () => ({
          task: _indexTask({ id: "index_task_1" }),
          scheduled: true
        }),
        getDocumentIndexTask: async () => _indexTask({ id: "index_task_1" }),
        retryDocumentIndexTask: async () => ({
          task: _indexTask({ id: "index_task_2", retryOfTaskId: "index_task_1" }),
          retriedFromTaskId: "index_task_1",
          scheduled: true
        }),
        deleteKnowledgeDocument: async () => ({ deleted: true, documentId: "doc_1" }),
        listChatSessions: async () => {
          calls.push("listChatSessions");
          return { items: [_chatSession()] };
        },
        getChatSession: async (sessionId) => {
          calls.push(`getChatSession:${sessionId}`);
          return {
            session: _chatSession({ id: sessionId }),
            messages: [_chatMessage({ sessionId })]
          };
        },
        createChatSession: async () => {
          calls.push("createChatSession");
          return _chatSession({ id: "chat_2", title: "New chat" });
        },
        appendChatMessage: async (sessionId, message) => {
          calls.push(`appendChatMessage:${sessionId}:${message.role}`);
          return {
            session: _chatSession({ id: sessionId, title: "Restart API" }),
            message: _chatMessage({ sessionId, role: message.role, content: message.content })
          };
        },
        streamChatMessage: _emptyChatStream,
        clearChatSession: async (sessionId) => {
          calls.push(`clearChatSession:${sessionId}`);
          return { sessionId, cleared: true, deletedMessages: 1 };
        },
        deleteChatSession: async (sessionId) => {
          calls.push(`deleteChatSession:${sessionId}`);
          return { sessionId, deleted: true };
        }
      }
    });

    await state.loadForCurrentUser();
    await state.selectChatSession("chat_1");
    await state.appendChatMessage("chat_1", {
      role: "user",
      content: "How do I restart the API?"
    });
    await state.clearChatSession("chat_1");
    const created = await state.createChatSession({ title: "New chat" });
    await state.deleteChatSession(created.id);

    expect(calls).toEqual([
      "listChatSessions",
      "getChatSession:chat_1",
      "appendChatMessage:chat_1:user",
      "getChatSession:chat_1",
      "clearChatSession:chat_1",
      "createChatSession",
      "getChatSession:chat_2",
      "deleteChatSession:chat_2"
    ]);
    expect(state.snapshot().chatSessions).toEqual([_chatSession()]);
    expect(state.snapshot().selectedChatSessionId).toBeNull();

    state.clear();

    expect(state.snapshot().chatSessions).toEqual([]);
    expect(state.snapshot().chatMessages).toEqual([]);
  });

  it("sends chat through streaming state and reconciles backend history", async () => {
    const calls: string[] = [];
    let state: ReturnType<typeof createProtectedDataState>;
    async function* streamChatMessage(): AsyncIterable<SseEvent> {
      calls.push("streamChatMessage:chat_1:How do I restart the API?");
      yield {
        id: "evt_delta_1",
        type: "content.delta",
        channel: "chat",
        timestamp: "2026-07-09T00:00:00.000Z",
        delta: "Use the ",
        sequence: 1
      };
      expect(state.snapshot().chatMessages.at(-1)?.content).toBe("Use the ");
      yield {
        id: "evt_reference_1",
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
      yield {
        id: "evt_delta_2",
        type: "content.delta",
        channel: "chat",
        timestamp: "2026-07-09T00:00:00.000Z",
        delta: "restart runbook.",
        sequence: 2
      };
      yield {
        id: "evt_complete_1",
        type: "complete",
        channel: "chat",
        timestamp: "2026-07-09T00:00:01.000Z",
        result: {
          session: _chatSession(),
          message: _chatMessage({
            role: "assistant",
            content: "Use the restart runbook.",
            metadata: {
              toolCallIds: ["tool_call_1"],
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
              ]
            }
          })
        }
      };
    }

    state = createProtectedDataState({
      client: {
        listKnowledgeBases: async () => ({ items: [] }),
        listKnowledgeDocuments: async () => ({ items: [] }),
        getKnowledgeDocument: async () => _document(),
        uploadKnowledgeDocument: async () => ({
          document: _document(),
          duplicateOfDocumentId: null,
          overwrite: false
        }),
        createDocumentIndexTask: async () => ({
          task: _indexTask({ id: "index_task_1" }),
          scheduled: true
        }),
        getDocumentIndexTask: async () => _indexTask({ id: "index_task_1" }),
        retryDocumentIndexTask: async () => ({
          task: _indexTask({ id: "index_task_2", retryOfTaskId: "index_task_1" }),
          retriedFromTaskId: "index_task_1",
          scheduled: true
        }),
        deleteKnowledgeDocument: async () => ({ deleted: true, documentId: "doc_1" }),
        listChatSessions: async () => ({ items: [_chatSession()] }),
        listChatToolCallAudits: async (sessionId) => {
          calls.push(`listChatToolCallAudits:${sessionId}`);
          return {
            items: [
              {
                id: "tool_call_1",
                ownerUserId: "user_1",
                sessionId,
                diagnosticTaskId: null,
                toolName: "knowledge_retrieval",
                status: "completed",
                arguments: { query: "restart api" },
                resultSummary: '{"results":["chunk_1"]}',
                errorMessage: null,
                startedAt: "2026-07-10T00:00:00.000Z",
                completedAt: "2026-07-10T00:00:00.100Z",
                durationMs: 100,
                createdAt: "2026-07-10T00:00:00.000Z"
              }
            ]
          };
        },
        getChatSession: async (sessionId) => {
          calls.push(`getChatSession:${sessionId}`);
          return {
            session: _chatSession({ id: sessionId }),
            messages: [
              _chatMessage({ sessionId, role: "user" }),
              _chatMessage({
                id: "message_2",
                sessionId,
                role: "assistant",
                content: "Use the restart runbook.",
                metadata: { toolCallIds: ["tool_call_1"] }
              })
            ]
          };
        },
        createChatSession: async () => _chatSession(),
        appendChatMessage: async () => ({ session: _chatSession(), message: _chatMessage() }),
        streamChatMessage,
        clearChatSession: async () => ({
          sessionId: "chat_1",
          cleared: true,
          deletedMessages: 0
        }),
        deleteChatSession: async () => ({ sessionId: "chat_1", deleted: true })
      }
    });

    await state.loadForCurrentUser();
    await state.selectChatSession("chat_1");
    await state.sendChatMessage("chat_1", { content: "How do I restart the API?" });

    expect(calls).toEqual([
      "getChatSession:chat_1",
      "listChatToolCallAudits:chat_1",
      "streamChatMessage:chat_1:How do I restart the API?",
      "getChatSession:chat_1"
      ,"listChatToolCallAudits:chat_1"
    ]);
    expect(state.snapshot().chatMessages.map((message) => message.role)).toEqual([
      "user",
      "assistant"
    ]);
    expect(state.snapshot().chatMessages[1]?.content).toBe("Use the restart runbook.");
    expect(state.snapshot().toolCallAudits[0]).toMatchObject({
      id: "tool_call_1",
      durationMs: 100,
      resultSummary: '{"results":["chunk_1"]}'
    });
  });
});

function _document(overrides: Partial<KnowledgeDocument> = {}): KnowledgeDocument {
  return {
    id: "doc_1",
    knowledgeBaseId: "kb_1",
    ownerUserId: "user_1",
    filename: "runbook.md",
    sizeBytes: 7,
    mimeType: "text/markdown",
    contentHash: "sha256:abc",
    status: "ready" as const,
    indexStatus: "pending" as const,
    uploadedAt: "2026-07-09T00:00:00.000Z",
    updatedAt: "2026-07-09T00:00:00.000Z",
    ...overrides
  };
}

function _indexTask(overrides: Partial<DocumentIndexTask> = {}): DocumentIndexTask {
  return {
    id: "index_task_1",
    ownerUserId: "user_1",
    knowledgeBaseId: "kb_1",
    documentId: "doc_1",
    status: "pending" as const,
    failureReason: null,
    retryOfTaskId: null,
    createdAt: "2026-07-09T00:00:00.000Z",
    updatedAt: "2026-07-09T00:00:00.000Z",
    startedAt: null,
    completedAt: null,
    ...overrides
  };
}

function _chatSession(overrides: Partial<ChatSessionSummary> = {}): ChatSessionSummary {
  return {
    id: "chat_1",
    ownerUserId: "user_1",
    title: "Restart API",
    createdAt: "2026-07-09T00:00:00.000Z",
    updatedAt: "2026-07-09T00:00:01.000Z",
    memory: {
      mode: "every_30_turns",
      contextTokens: 1200,
      contextWindowTokens: 131072,
      contextUsagePercent: 0.9,
      compactedMessageCount: 0,
      lastCompactedAt: null,
      canCompact: true
    },
    ...overrides
  };
}

function _chatMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "message_1",
    ownerUserId: "user_1",
    sessionId: "chat_1",
    role: "user",
    content: "How do I restart the API?",
    metadata: {
      toolCallIds: ["tool_call_1"],
      custom: { source: "manual" }
    },
    createdAt: "2026-07-09T00:00:00.000Z",
    ...overrides
  };
}

function _sseStream(
  events: Array<{ readonly event: string; readonly data: SseEvent }>
): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const item of events) {
        controller.enqueue(
          encoder.encode(`event: ${item.event}\ndata: ${JSON.stringify(item.data)}\n\n`)
        );
      }
      controller.close();
    }
  });
}

async function* _emptyChatStream(): AsyncIterable<SseEvent> {
  return;
}
