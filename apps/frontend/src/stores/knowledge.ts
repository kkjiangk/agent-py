import { ref } from "vue";
import { defineStore } from "pinia";

import type {
  DocumentIndexTask,
  DocumentChunkingConfiguration,
  DocumentChunkPreview,
  KnowledgeBaseSummary,
  KnowledgeDocument
} from "@agent-py/api-contracts";

import { ApiClientError } from "../api/apiClient";
import { createKnowledgeClient, type KnowledgeClient } from "../knowledge/knowledgeClient";
import { useFeedbackStore } from "./feedback";
import { toUserFacingError } from "../ui/userFacingError";

const POLL_INTERVAL_MS = 2_000;

let clientFactory: () => KnowledgeClient = createKnowledgeClient;

export function setKnowledgeClientFactoryForTests(factory: (() => KnowledgeClient) | null): void {
  clientFactory = factory ?? createKnowledgeClient;
}

export const useKnowledgeStore = defineStore("knowledge", () => {
  const client = clientFactory();
  const knowledgeBases = ref<readonly KnowledgeBaseSummary[]>([]);
  const selectedKnowledgeBaseId = ref<string | null>(null);
  const documents = ref<readonly KnowledgeDocument[]>([]);
  const indexTasks = ref<readonly DocumentIndexTask[]>([]);
  const selectedDocument = ref<KnowledgeDocument | null>(null);
  const pendingOverwriteFile = ref<File | null>(null);
  const pendingOverwriteChunking = ref<DocumentChunkingConfiguration | null>(null);
  const chunkPreview = ref<DocumentChunkPreview | null>(null);
  const isLoading = ref(false);
  const isUploading = ref(false);
  const errorMessage = ref<string | null>(null);
  const timers = new Map<string, ReturnType<typeof globalThis.setInterval>>();

  function reportError(error: unknown): void {
    const message = toUserFacingError(error);
    errorMessage.value = message;
    useFeedbackStore().showError(message);
  }

  function upsertTask(task: DocumentIndexTask): void {
    indexTasks.value = [task, ...indexTasks.value.filter((item) => item.id !== task.id)];
  }

  function upsertDocument(document: KnowledgeDocument): void {
    documents.value = [document, ...documents.value.filter((item) => item.id !== document.id)];
  }

  function isActive(task: DocumentIndexTask): boolean {
    return task.status === "pending" || task.status === "running";
  }

  function stopTaskPolling(taskId: string): void {
    const timer = timers.get(taskId);
    if (timer !== undefined) {
      globalThis.clearInterval(timer);
      timers.delete(taskId);
    }
  }

  async function refreshIndexTask(task: DocumentIndexTask): Promise<void> {
    const refreshed = await client.getIndexTask({
      documentId: task.documentId,
      knowledgeBaseId: task.knowledgeBaseId,
      taskId: task.id
    });
    upsertTask(refreshed);
    if (!isActive(refreshed)) {
      stopTaskPolling(refreshed.id);
    }
  }

  function scheduleTaskPolling(task: DocumentIndexTask): void {
    stopTaskPolling(task.id);
    if (!isActive(task)) {
      return;
    }
    const timer = globalThis.setInterval(() => {
      void refreshIndexTask(task).catch(reportError);
    }, POLL_INTERVAL_MS);
    timers.set(task.id, timer);
  }

  async function trackIndexTask(task: DocumentIndexTask): Promise<void> {
    upsertTask(task);
    scheduleTaskPolling(task);
  }

  async function loadDocuments(knowledgeBaseId: string): Promise<void> {
    const response = await client.listKnowledgeDocuments(knowledgeBaseId);
    documents.value = response.items;
    indexTasks.value = indexTasks.value.filter((task) => task.knowledgeBaseId === knowledgeBaseId);
    selectedDocument.value = selectedDocument.value === null
      ? null
      : documents.value.find((document) => document.id === selectedDocument.value?.id) ?? null;
  }

  function reset(): void {
    for (const taskId of timers.keys()) {
      stopTaskPolling(taskId);
    }
    knowledgeBases.value = [];
    selectedKnowledgeBaseId.value = null;
    documents.value = [];
    indexTasks.value = [];
    selectedDocument.value = null;
    pendingOverwriteFile.value = null;
    pendingOverwriteChunking.value = null;
    chunkPreview.value = null;
    isLoading.value = false;
    isUploading.value = false;
    errorMessage.value = null;
  }

  async function upload(file: File, chunking: DocumentChunkingConfiguration = { strategy: "fixed-character", maxCharacters: 1200, overlapCharacters: 200 }, overwrite = false): Promise<void> {
    const knowledgeBaseId = selectedKnowledgeBaseId.value;
    if (knowledgeBaseId === null) {
      const error = new Error("未找到可用的知识库。");
      reportError(error);
      throw error;
    }
    isUploading.value = true;
    errorMessage.value = null;
    try {
      const response = await client.uploadDocument({ file, knowledgeBaseId, overwrite, chunking });
      pendingOverwriteFile.value = null;
      pendingOverwriteChunking.value = null;
      upsertDocument(response.document);
      chunkPreview.value = await (client.getChunkPreview?.({ documentId: response.document.id, knowledgeBaseId }) ?? Promise.resolve(null));
      const indexResponse = await client.createIndexTask({
        documentId: response.document.id,
        knowledgeBaseId: response.document.knowledgeBaseId
      });
      await trackIndexTask(indexResponse.task);
    } catch (error) {
      if (error instanceof ApiClientError && error.error.code === "BUSINESS_CONFLICT" && !overwrite) {
        pendingOverwriteFile.value = file;
        pendingOverwriteChunking.value = chunking;
      }
      reportError(error);
      throw error;
    } finally {
      isUploading.value = false;
    }
  }

  return {
    documents,
    errorMessage,
    indexTasks,
    isLoading,
    isUploading,
    knowledgeBases,
    pendingOverwriteFile,
    chunkPreview,
    selectedDocument,
    selectedKnowledgeBaseId,
    initialize: async (): Promise<void> => {
      isLoading.value = true;
      errorMessage.value = null;
      try {
        knowledgeBases.value = (await client.listKnowledgeBases()).items;
        const selected = knowledgeBases.value.find((base) => base.id === selectedKnowledgeBaseId.value) ?? knowledgeBases.value[0];
        if (selected === undefined) {
          selectedKnowledgeBaseId.value = null;
          documents.value = [];
          return;
        }
        selectedKnowledgeBaseId.value = selected.id;
        await loadDocuments(selected.id);
      } catch (error) {
        reset();
        reportError(error);
        throw error;
      } finally {
        isLoading.value = false;
      }
    },
    selectKnowledgeBase: async (knowledgeBaseId: string): Promise<void> => {
      isLoading.value = true;
      try {
        selectedKnowledgeBaseId.value = knowledgeBaseId;
        selectedDocument.value = null;
        await loadDocuments(knowledgeBaseId);
      } catch (error) {
        reportError(error);
        throw error;
      } finally {
        isLoading.value = false;
      }
    },
    openDocument: async (document: KnowledgeDocument): Promise<void> => {
      try {
        selectedDocument.value = await client.getDocument({
          documentId: document.id,
          knowledgeBaseId: document.knowledgeBaseId
        });
        chunkPreview.value = await (client.getChunkPreview?.({ documentId: document.id, knowledgeBaseId: document.knowledgeBaseId }) ?? Promise.resolve(null));
      } catch (error) {
        reportError(error);
        throw error;
      }
    },
    closeDocument: (): void => {
      selectedDocument.value = null;
    },
    trackIndexTask,
    upload,
    overwritePendingUpload: async (): Promise<void> => {
      const file = pendingOverwriteFile.value;
      if (file !== null) {
        await upload(file, pendingOverwriteChunking.value ?? undefined, true);
      }
    },
    clearPendingOverwrite: (): void => {
      pendingOverwriteFile.value = null;
      pendingOverwriteChunking.value = null;
    },
    rebuildDocumentIndex: async (document: KnowledgeDocument): Promise<void> => {
      try {
        const response = await client.createIndexTask({
          documentId: document.id,
          knowledgeBaseId: document.knowledgeBaseId
        });
        await trackIndexTask(response.task);
      } catch (error) {
        reportError(error);
        throw error;
      }
    },
    retryIndexTask: async (task: DocumentIndexTask): Promise<void> => {
      try {
        const response = await client.retryIndexTask({
          documentId: task.documentId,
          knowledgeBaseId: task.knowledgeBaseId,
          taskId: task.id
        });
        await trackIndexTask(response.task);
      } catch (error) {
        reportError(error);
        throw error;
      }
    },
    deleteDocument: async (document: KnowledgeDocument): Promise<void> => {
      try {
        await client.deleteDocument({
          documentId: document.id,
          knowledgeBaseId: document.knowledgeBaseId
        });
        documents.value = documents.value.filter((item) => item.id !== document.id);
        for (const task of indexTasks.value.filter((item) => item.documentId === document.id)) {
          stopTaskPolling(task.id);
        }
        indexTasks.value = indexTasks.value.filter((item) => item.documentId !== document.id);
        if (selectedDocument.value?.id === document.id) {
          selectedDocument.value = null;
        }
      } catch (error) {
        reportError(error);
        throw error;
      }
    },
    reset,
    stopPolling: (): void => {
      for (const taskId of timers.keys()) {
        stopTaskPolling(taskId);
      }
    }
  };
});
