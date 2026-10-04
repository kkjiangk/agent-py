import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  DocumentIndexTask,
  KnowledgeBaseSummary,
  KnowledgeDocument
} from "@agent-py/api-contracts";

import type { KnowledgeClient } from "../src/knowledge/knowledgeClient";
import {
  setKnowledgeClientFactoryForTests,
  useKnowledgeStore
} from "../src/stores/knowledge";

const base = (overrides: Partial<KnowledgeBaseSummary> = {}): KnowledgeBaseSummary => ({
  id: "kb_1",
  name: "Operations runbooks",
  ownerUserId: "user_1",
  ...overrides
});

const document = (overrides: Partial<KnowledgeDocument> = {}): KnowledgeDocument => ({
  id: "doc_1",
  knowledgeBaseId: "kb_1",
  ownerUserId: "user_1",
  filename: "restart.md",
  sizeBytes: 42,
  mimeType: "text/markdown",
  contentHash: "sha256:abc",
  status: "ready",
  indexStatus: "indexed",
  uploadedAt: "2026-07-10T00:00:00.000Z",
  updatedAt: "2026-07-10T00:00:00.000Z",
  source: "upload",
  ...overrides
});

const task = (overrides: Partial<DocumentIndexTask> = {}): DocumentIndexTask => ({
  id: "task_1",
  ownerUserId: "user_1",
  knowledgeBaseId: "kb_1",
  documentId: "doc_1",
  status: "pending",
  failureReason: null,
  retryOfTaskId: null,
  createdAt: "2026-07-10T00:00:00.000Z",
  updatedAt: "2026-07-10T00:00:00.000Z",
  startedAt: null,
  completedAt: null,
  ...overrides
});

afterEach(() => {
  setKnowledgeClientFactoryForTests(null);
  vi.useRealTimers();
});

describe("knowledge store", () => {
  it("loads the selected knowledge base documents from the backend", async () => {
    setKnowledgeClientFactoryForTests(() => fakeClient());
    setActivePinia(createPinia());
    const store = useKnowledgeStore();

    await store.initialize();

    expect(store.knowledgeBases).toEqual([base()]);
    expect(store.selectedKnowledgeBaseId).toBe("kb_1");
    expect(store.documents).toEqual([document()]);
  });

  it("uploads a document and tracks its returned index task without blocking the workspace", async () => {
    const client = fakeClient();
    setKnowledgeClientFactoryForTests(() => client);
    setActivePinia(createPinia());
    const store = useKnowledgeStore();
    await store.initialize();

    await store.upload(new File(["restart service"], "restart.md", { type: "text/markdown" }));

    expect(client.uploadDocument).toHaveBeenCalledWith(expect.objectContaining({
      knowledgeBaseId: "kb_1",
      overwrite: false
    }));
    expect(client.createIndexTask).toHaveBeenCalledWith({ documentId: "doc_1", knowledgeBaseId: "kb_1" });
    expect(store.indexTasks).toEqual([task()]);
    expect(store.isUploading).toBe(false);
  });

  it("polls active tasks, renders failures, and retries through the typed client", async () => {
    vi.useFakeTimers();
    const client = fakeClient({
      taskResult: task({ failureReason: "Embedding unavailable", status: "failed" })
    });
    setKnowledgeClientFactoryForTests(() => client);
    setActivePinia(createPinia());
    const store = useKnowledgeStore();
    await store.initialize();
    await store.trackIndexTask(task());

    await vi.advanceTimersByTimeAsync(2_000);

    expect(store.indexTasks[0]).toEqual(task({ failureReason: "Embedding unavailable", status: "failed" }));
    await store.retryIndexTask(task({ failureReason: "Embedding unavailable", status: "failed" }));
    expect(client.retryIndexTask).toHaveBeenCalledWith({
      documentId: "doc_1",
      knowledgeBaseId: "kb_1",
      taskId: "task_1"
    });
  });

  it("removes a document only after the backend confirms deletion", async () => {
    const client = fakeClient();
    setKnowledgeClientFactoryForTests(() => client);
    setActivePinia(createPinia());
    const store = useKnowledgeStore();
    await store.initialize();

    await store.deleteDocument(document());

    expect(client.deleteDocument).toHaveBeenCalledWith({ documentId: "doc_1", knowledgeBaseId: "kb_1" });
    expect(store.documents).toEqual([]);
  });
});

function fakeClient(options: { readonly taskResult?: DocumentIndexTask } = {}): KnowledgeClient & {
  readonly uploadDocument: ReturnType<typeof vi.fn>;
  readonly createIndexTask: ReturnType<typeof vi.fn>;
  readonly deleteDocument: ReturnType<typeof vi.fn>;
  readonly retryIndexTask: ReturnType<typeof vi.fn>;
} {
  return {
    createIndexTask: vi.fn(async () => ({ scheduled: true, task: task() })),
    deleteDocument: vi.fn(async () => ({ deleted: true as const, documentId: "doc_1" })),
    getIndexTask: vi.fn(async () => options.taskResult ?? task({ status: "succeeded" })),
    getDocument: vi.fn(async () => document()),
    listKnowledgeBases: vi.fn(async () => ({ items: [base()] })),
    listKnowledgeDocuments: vi.fn(async () => ({ items: [document()] })),
    retryIndexTask: vi.fn(async () => ({
      retriedFromTaskId: "task_1",
      scheduled: true,
      task: task({ id: "task_2", retryOfTaskId: "task_1" })
    })),
    uploadDocument: vi.fn(async () => ({
      document: document({ indexStatus: "pending" }),
      duplicateOfDocumentId: null,
      overwrite: false
    }))
  };
}
