import { computed, ref } from "vue";
import { defineStore } from "pinia";

import type {
  ChatMessage,
  ChatAssemblyConfigurationResponse,
  ChatSessionSummary,
  ChatMemoryMode,
  ReferenceSourceSseEvent,
  ToolCallAudit
} from "@agent-py/api-contracts";

import { ApiClientError } from "../api/apiClient";
import { createChatClient, type ChatClient } from "../chat/chatClient";
import { useFeedbackStore } from "./feedback";
import { toUserFacingError } from "../ui/userFacingError";

export type ChatReference = ReferenceSourceSseEvent["reference"];

export interface LiveToolCall {
  readonly id: string;
  readonly name: string;
  readonly status: "started" | "delta" | "completed" | "failed";
  readonly input?: unknown;
  readonly output?: unknown;
}

let clientFactory: () => ChatClient = createChatClient;
export const CHAT_TYPEWRITER_DELAY_MS = 28;

export function setChatClientFactoryForTests(factory: (() => ChatClient) | null): void {
  clientFactory = factory ?? createChatClient;
}

export const useChatStore = defineStore("chat", () => {
  const client = clientFactory();
  const sessions = ref<readonly ChatSessionSummary[]>([]);
  const activeSessionId = ref<string | null>(null);
  const messages = ref<readonly ChatMessage[]>([]);
  const toolAudits = ref<readonly ToolCallAudit[]>([]);
  const liveToolCalls = ref<readonly LiveToolCall[]>([]);
  const references = ref<readonly ChatReference[]>([]);
  const isLoading = ref(false);
  const isSending = ref(false);
  const isUpdatingMemory = ref(false);
  const errorMessage = ref<string | null>(null);
  const configuration = ref<ChatAssemblyConfigurationResponse | null>(null);
  const isSavingConfiguration = ref(false);
  const activeSession = computed(
    () => sessions.value.find((item) => item.id === activeSessionId.value) ?? null
  );

  function reportError(error: unknown): void {
    const message = toUserFacingError(error);
    errorMessage.value = message;
    useFeedbackStore().showError(message);
  }

  function setReferencesFromMessages(nextMessages: readonly ChatMessage[]): void {
    const latestAssistant = [...nextMessages]
      .reverse()
      .find((item) => item.role === "assistant");
    references.value = uniqueReferences(latestAssistant?.metadata.citations ?? []);
  }

  async function loadSession(sessionId: string): Promise<void> {
    const [detail, audits] = await Promise.all([
      client.getSession(sessionId),
      client.listToolCallAudits(sessionId)
    ]);
    activeSessionId.value = detail.session.id;
    messages.value = detail.messages;
    toolAudits.value = audits.items;
    liveToolCalls.value = [];
    setReferencesFromMessages(detail.messages);
    upsertSession(detail.session);
  }

  function upsertSession(nextSession: ChatSessionSummary): void {
    sessions.value = [
      nextSession,
      ...sessions.value.filter((item) => item.id !== nextSession.id)
    ].sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
  }

  async function reloadSessions(): Promise<void> {
    sessions.value = (await client.listSessions()).items;
  }

  function reset(): void {
    sessions.value = [];
    activeSessionId.value = null;
    messages.value = [];
    toolAudits.value = [];
    liveToolCalls.value = [];
    references.value = [];
    errorMessage.value = null;
    configuration.value = null;
    isSavingConfiguration.value = false;
    isLoading.value = false;
    isSending.value = false;
    isUpdatingMemory.value = false;
  }

  return {
    activeSessionId,
    activeSession,
    errorMessage,
    configuration,
    isSavingConfiguration,
    isLoading,
    isSending,
    isUpdatingMemory,
    liveToolCalls,
    messages,
    references,
    sessions,
    toolAudits,
    initialize: async (): Promise<void> => {
      isLoading.value = true;
      errorMessage.value = null;
      try {
        const [loadedConfiguration] = await Promise.all([client.getConfiguration?.() ?? Promise.resolve(null), reloadSessions()]);
        configuration.value = loadedConfiguration;
        const selected = sessions.value.find((item) => item.id === activeSessionId.value) ?? sessions.value[0];
        if (selected !== undefined) {
          await loadSession(selected.id);
        } else {
          messages.value = [];
          toolAudits.value = [];
          references.value = [];
        }
      } catch (error) {
        reportError(error);
        throw error;
      } finally {
        isLoading.value = false;
      }
    },
    newSession: async (): Promise<ChatSessionSummary> => {
      try {
        const created = await client.createSession({});
        upsertSession(created);
        activeSessionId.value = created.id;
        messages.value = [];
        toolAudits.value = [];
        liveToolCalls.value = [];
        references.value = [];
        return created;
      } catch (error) {
        reportError(error);
        throw error;
      }
    },
    selectSession: async (sessionId: string): Promise<void> => {
      isLoading.value = true;
      try {
        await loadSession(sessionId);
      } catch (error) {
        reportError(error);
        throw error;
      } finally {
        isLoading.value = false;
      }
    },
    deleteSession: async (sessionId: string): Promise<void> => {
      try {
        await client.deleteSession(sessionId);
        sessions.value = sessions.value.filter((item) => item.id !== sessionId);
        if (activeSessionId.value === sessionId) {
          const nextSession = sessions.value[0];
          if (nextSession === undefined) {
            activeSessionId.value = null;
            messages.value = [];
            toolAudits.value = [];
            references.value = [];
          } else {
            await loadSession(nextSession.id);
          }
        }
      } catch (error) {
        reportError(error);
        throw error;
      }
    },
    saveConfiguration: async (systemPromptId: string, skillIds: readonly string[]): Promise<void> => {
      isSavingConfiguration.value = true;
      try {
        if (client.updateConfiguration === undefined) return;
        configuration.value = await client.updateConfiguration({ systemPromptId, skillIds });
      } catch (error) {
        reportError(error);
        throw error;
      } finally {
        isSavingConfiguration.value = false;
      }
    },
    createPrompt: async (label: string, content: string): Promise<void> => {
      isSavingConfiguration.value = true;
      try {
        if (client.createPrompt === undefined || client.getConfiguration === undefined) return;
        await client.createPrompt({ label, content });
        configuration.value = await client.getConfiguration();
      } catch (error) {
        reportError(error);
        throw error;
      } finally {
        isSavingConfiguration.value = false;
      }
    },
    updatePrompt: async (promptId: string, label: string, content: string): Promise<void> => {
      isSavingConfiguration.value = true;
      try {
        if (client.updatePrompt === undefined || client.getConfiguration === undefined) return;
        await client.updatePrompt(promptId, { label, content });
        configuration.value = await client.getConfiguration();
      } catch (error) {
        reportError(error);
        throw error;
      } finally {
        isSavingConfiguration.value = false;
      }
    },
    deletePrompt: async (promptId: string): Promise<void> => {
      isSavingConfiguration.value = true;
      try {
        if (client.deletePrompt === undefined || client.getConfiguration === undefined) return;
        await client.deletePrompt(promptId);
        configuration.value = await client.getConfiguration();
      } catch (error) {
        reportError(error);
        throw error;
      } finally {
        isSavingConfiguration.value = false;
      }
    },
    uploadSkill: async (file: File): Promise<void> => {
      isSavingConfiguration.value = true;
      try {
        if (client.uploadSkill === undefined || client.getConfiguration === undefined) return;
        await client.uploadSkill(file);
        configuration.value = await client.getConfiguration();
      } catch (error) {
        reportError(error);
        throw error;
      } finally {
        isSavingConfiguration.value = false;
      }
    },
    deleteSkill: async (skillId: string): Promise<void> => {
      isSavingConfiguration.value = true;
      try {
        if (client.deleteSkill === undefined || client.getConfiguration === undefined) return;
        await client.deleteSkill(skillId);
        configuration.value = await client.getConfiguration();
      } catch (error) {
        reportError(error);
        throw error;
      } finally {
        isSavingConfiguration.value = false;
      }
    },
    reset,
    updateMemoryMode: async (mode: ChatMemoryMode): Promise<void> => {
      const sessionId = activeSessionId.value;
      if (sessionId === null || isUpdatingMemory.value) return;
      isUpdatingMemory.value = true;
      try {
        const updated = await client.updateMemoryMode(sessionId, mode);
        upsertSession(updated);
      } catch (error) {
        reportError(error);
        throw error;
      } finally {
        isUpdatingMemory.value = false;
      }
    },
    compactMemory: async (): Promise<void> => {
      const sessionId = activeSessionId.value;
      if (sessionId === null || isUpdatingMemory.value) return;
      isUpdatingMemory.value = true;
      try {
        const updated = await client.compactMemory(sessionId);
        upsertSession(updated);
      } catch (error) {
        reportError(error);
        throw error;
      } finally {
        isUpdatingMemory.value = false;
      }
    },
    send: async (rawContent: string): Promise<void> => {
      const content = rawContent.trim();
      if (content.length === 0 || isSending.value) {
        return;
      }
      if ((activeSession.value?.memory.contextUsagePercent ?? 0) >= 95) {
        reportError(new Error("上下文已达到 95%，请执行手动压缩后再继续对话。"));
        return;
      }
      try {
        const targetSessionId = activeSessionId.value ?? (await createNewSession(client, upsertSession));
        if (activeSessionId.value === null) {
          activeSessionId.value = targetSessionId;
        }
        isSending.value = true;
        errorMessage.value = null;
        references.value = [];
        const optimisticUser = createOptimisticMessage(targetSessionId, "user", content);
        const draftId = `message_draft_${Date.now()}`;
        messages.value = [...messages.value, optimisticUser];
        let finished = false;
        for await (const event of client.streamMessage(targetSessionId, { content })) {
          if (event.type === "content.delta") {
            for (const character of event.delta) {
              updateAssistantDraft(targetSessionId, draftId, character, messages);
              await waitForTypewriterTick();
            }
          }
          if (event.type === "reasoning.delta") {
            updateAssistantReasoning(targetSessionId, draftId, event.delta, messages);
          }
          if (event.type === "reference.source") {
            references.value = uniqueReferences([...references.value, event.reference]);
          }
          if (event.type === "tool.call") {
            updateLiveToolCall(event.toolCall, liveToolCalls);
          }
          if (event.type === "error") {
            throw new ApiClientError(event.error);
          }
          if (event.type === "complete") {
            finished = true;
          }
        }
        if (!finished) {
          throw new Error("回答流在完成前意外中断。");
        }
        await Promise.all([loadSession(targetSessionId), reloadSessions()]);
      } catch (error) {
        messages.value = messages.value.filter((item) => !item.id.startsWith("message_draft_"));
        reportError(error);
        throw error;
      } finally {
        isSending.value = false;
        liveToolCalls.value = [];
      }
    }
  };
});

async function createNewSession(
  client: ChatClient,
  upsert: (session: ChatSessionSummary) => void
): Promise<string> {
  const session = await client.createSession({});
  upsert(session);
  return session.id;
}

function createOptimisticMessage(
  sessionId: string,
  role: ChatMessage["role"],
  content: string
): ChatMessage {
  return {
    id: `message_optimistic_${Date.now()}`,
    ownerUserId: "current",
    sessionId,
    role,
    content,
    metadata: {},
    createdAt: new Date().toISOString()
  };
}

function updateAssistantDraft(
  sessionId: string,
  draftId: string,
  delta: string,
  target: { value: readonly ChatMessage[] }
): void {
  const existing = target.value.find((item) => item.id === draftId);
  const draft: ChatMessage = {
    id: draftId,
    ownerUserId: "current",
    sessionId,
    role: "assistant",
    content: `${existing?.content ?? ""}${delta}`,
    metadata: { citations: [] },
    createdAt: existing?.createdAt ?? new Date().toISOString()
  };
  target.value = existing === undefined
    ? [...target.value, draft]
    : target.value.map((item) => (item.id === draftId ? draft : item));
}

function updateAssistantReasoning(
  sessionId: string,
  draftId: string,
  delta: string,
  target: { value: readonly ChatMessage[] }
): void {
  const existing = target.value.find((item) => item.id === draftId);
  const draft: ChatMessage = {
    id: draftId,
    ownerUserId: "current",
    sessionId,
    role: "assistant",
    content: existing?.content ?? "",
    metadata: {
      ...existing?.metadata,
      citations: existing?.metadata.citations ?? [],
      reasoning: [...(existing?.metadata.reasoning ?? []), delta]
    },
    createdAt: existing?.createdAt ?? new Date().toISOString()
  };
  target.value = existing === undefined
    ? [...target.value, draft]
    : target.value.map((item) => (item.id === draftId ? draft : item));
}

function updateLiveToolCall(
  next: LiveToolCall,
  target: { value: readonly LiveToolCall[] }
): void {
  const existing = target.value.find((item) => item.id === next.id);
  const merged: LiveToolCall = {
    ...existing,
    ...next,
    ...(next.input === undefined ? {} : { input: next.input }),
    ...(next.output === undefined ? {} : { output: next.output })
  };
  target.value = [merged, ...target.value.filter((item) => item.id !== next.id)];
}

function uniqueReferences(items: readonly ChatReference[]): readonly ChatReference[] {
  const seen = new Set<string>();
  return items
    .filter((item) => {
      if (seen.has(item.id)) {
        return false;
      }
      seen.add(item.id);
      return true;
    })
    .sort((left, right) => referenceScore(right) - referenceScore(left))
    .slice(0, 5);
}

function referenceScore(reference: ChatReference): number {
  return reference.rerankScore ?? reference.score ?? Number.NEGATIVE_INFINITY;
}

function waitForTypewriterTick(): Promise<void> {
  return new Promise((resolve) => {
    globalThis.setTimeout(resolve, CHAT_TYPEWRITER_DELAY_MS);
  });
}
