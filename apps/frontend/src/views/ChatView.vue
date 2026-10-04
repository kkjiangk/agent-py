<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useRouter } from "vue-router";

import type { ReferenceSourceSseEvent } from "@agent-py/api-contracts";

import ChatComposer from "../components/ChatComposer.vue";
import ChatPromptSidebar from "../components/ChatPromptSidebar.vue";
import ChatSkillSidebar from "../components/ChatSkillSidebar.vue";
import ChatTranscript from "../components/ChatTranscript.vue";
import { useChatStore } from "../stores/chat";

const chat = useChatStore();
const router = useRouter();
const activeTitle = computed(() =>
  chat.sessions.find((session) => session.id === chat.activeSessionId)?.title ?? "新对话"
);

onMounted(() => {
  void chat.initialize().catch(() => undefined);
});

function run(operation: () => Promise<unknown>): void {
  void operation().catch(() => undefined);
}

function openCitationDocument(reference: ReferenceSourceSseEvent["reference"]): void {
  if (reference.documentId === undefined || reference.knowledgeBaseId === undefined) return;
  void router.push({
    name: "knowledge",
    query: { documentId: reference.documentId, knowledgeBaseId: reference.knowledgeBaseId }
  });
}

function saveChatConfiguration(systemPromptId: string, skillIds: readonly string[]): void {
  run(() => chat.saveConfiguration(systemPromptId, skillIds));
}

</script>

<template>
  <section class="chat-view" aria-label="对话工作区">
    <div class="chat-view__conversation">
      <header><p>当前对话</p><h2>{{ activeTitle }}</h2></header>
      <ChatTranscript
        :is-loading="chat.isLoading"
        :live-tool-calls="chat.liveToolCalls"
        :messages="chat.messages"
        :references="chat.references"
        :tool-audits="chat.toolAudits"
        @open-document="openCitationDocument"
      />
      <ChatComposer
        :disabled="chat.isLoading"
        :is-sending="chat.isSending"
        :is-updating-memory="chat.isUpdatingMemory"
        :memory="chat.activeSession?.memory ?? null"
        @apply-memory="run(() => chat.updateMemoryMode($event))"
        @compact-memory="run(() => chat.compactMemory())"
        @send="run(() => chat.send($event))"
      />
    </div>
    <div class="chat-view__settings">
      <ChatPromptSidebar
        :configuration="chat.configuration"
        :is-saving="chat.isSavingConfiguration"
        @create-prompt="(label, content) => run(() => chat.createPrompt(label, content))"
        @delete-prompt="run(() => chat.deletePrompt($event))"
        @save="saveChatConfiguration"
        @update-prompt="(promptId, label, content) => run(() => chat.updatePrompt(promptId, label, content))"
      />
      <ChatSkillSidebar
        :configuration="chat.configuration"
        :is-saving="chat.isSavingConfiguration"
        @delete-skill="run(() => chat.deleteSkill($event))"
        @save="saveChatConfiguration"
        @upload-skill="run(() => chat.uploadSkill($event))"
      />
    </div>
  </section>
</template>

<style scoped>
.chat-view { background: var(--surface-raised); display: grid; grid-template-columns: minmax(0, 1fr) minmax(18rem, 22rem); height: 100%; overflow: hidden; }
.chat-view__conversation { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; min-height: 0; min-width: 0; }
.chat-view__conversation > header { align-items: center; border-bottom: 1px solid var(--line); display: flex; justify-content: space-between; min-height: 3.75rem; padding: 0.75rem clamp(1rem, 3vw, 2rem); }
.chat-view__conversation > header p { color: var(--text-tertiary); font-size: 0.72rem; font-weight: 650; margin: 0; }
.chat-view__conversation > header h2 { font-size: 0.92rem; font-weight: 660; margin: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chat-view__settings { display: grid; grid-template-rows: minmax(0, 1fr) minmax(0, 1fr); min-height: 0; min-width: 0; }
.chat-view :deep(button:focus), .chat-view :deep(a:focus), .chat-view :deep(input:focus), .chat-view :deep(select:focus), .chat-view :deep(textarea:focus), .chat-view :deep(button:focus-visible), .chat-view :deep(a:focus-visible), .chat-view :deep(input:focus-visible), .chat-view :deep(select:focus-visible), .chat-view :deep(textarea:focus-visible) { outline: none; outline-offset: 0; }
@media (max-width: 1120px) { .chat-view { grid-template-columns: minmax(0, 1fr); height: auto; } .chat-view__conversation { min-height: 36rem; } .chat-view__settings { grid-column: 1; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); grid-template-rows: auto; } }
</style>
