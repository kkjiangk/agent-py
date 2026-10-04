<script setup lang="ts">
import { Check, ChevronDown, ChevronRight, Pencil, Plus, Trash2 } from "lucide-vue-next";
import { computed, reactive, ref, watch } from "vue";

import type { ChatAssemblyConfigurationResponse } from "@agent-py/api-contracts";

const emit = defineEmits<{
  save: [systemPromptId: string, skillIds: readonly string[]];
  createPrompt: [label: string, content: string];
  updatePrompt: [promptId: string, label: string, content: string];
  deletePrompt: [promptId: string];
}>();
const props = defineProps<{
  readonly configuration: ChatAssemblyConfigurationResponse | null;
  readonly isSaving: boolean;
}>();

interface PromptDraft {
  label: string;
  content: string;
}

const expandedIds = ref<ReadonlySet<string>>(new Set());
const drafts = reactive<Record<string, PromptDraft>>({});
const newPrompt = reactive<PromptDraft>({ label: "", content: "" });
const isCreating = ref(false);
const localNotice = ref<string | null>(null);
const hasInitializedExpansion = ref(false);

const selectedPromptId = computed(() => props.configuration?.selection.systemPromptId ?? "");
const selectedSkillIds = computed(() => props.configuration?.selection.skillIds ?? []);

watch(
  () => props.configuration,
  (value) => {
    if (value === null) return;
    for (const prompt of value.prompts) {
      drafts[prompt.id] = { label: prompt.label, content: prompt.content };
    }
    if (!hasInitializedExpansion.value) {
      if (value.selection.systemPromptId.length > 0) {
        expandedIds.value = new Set([value.selection.systemPromptId]);
      }
      hasInitializedExpansion.value = true;
    }
  },
  { immediate: true }
);

function isExpanded(promptId: string): boolean {
  return expandedIds.value.has(promptId);
}

function togglePrompt(promptId: string): void {
  const next = new Set(expandedIds.value);
  if (next.has(promptId)) {
    next.delete(promptId);
  } else {
    next.add(promptId);
  }
  expandedIds.value = next;
}

function createPrompt(): void {
  const label = newPrompt.label.trim();
  const content = newPrompt.content.trim();
  if (label.length === 0 || content.length === 0) {
    localNotice.value = "请填写提示词名称和内容。";
    return;
  }
  localNotice.value = null;
  emit("createPrompt", label, content);
  newPrompt.label = "";
  newPrompt.content = "";
  isCreating.value = false;
}

function updatePrompt(promptId: string): void {
  const draft = drafts[promptId];
  if (draft === undefined) return;
  const label = draft.label.trim();
  const content = draft.content.trim();
  if (label.length === 0 || content.length === 0) {
    localNotice.value = "请填写提示词名称和内容。";
    return;
  }
  localNotice.value = null;
  emit("updatePrompt", promptId, label, content);
}

function updateDraftLabel(promptId: string, event: Event): void {
  const draft = drafts[promptId];
  if (draft === undefined) return;
  draft.label = (event.target as HTMLInputElement).value;
}

function updateDraftContent(promptId: string, event: Event): void {
  const draft = drafts[promptId];
  if (draft === undefined) return;
  draft.content = (event.target as HTMLTextAreaElement).value;
}

function usePrompt(promptId: string): void {
  emit("save", promptId, selectedSkillIds.value);
}
</script>

<template>
  <aside class="chat-prompt-sidebar" aria-label="对话系统提示词设置">
    <header class="chat-prompt-sidebar__header">
      <div>
        <p>对话系统提示词设置</p>
        <h3>单选一个系统提示词</h3>
      </div>
      <button type="button" title="新建提示词" :disabled="isSaving" @click="isCreating = !isCreating">
        <Plus :size="16" aria-hidden="true" />
      </button>
    </header>

    <p v-if="localNotice" class="chat-prompt-sidebar__notice" role="alert">{{ localNotice }}</p>
    <p v-if="configuration === null" class="chat-prompt-sidebar__empty">正在加载提示词。</p>

    <section v-if="isCreating" class="chat-prompt-sidebar__creator" aria-label="新建系统提示词">
      <label>名称<input v-model="newPrompt.label" :disabled="isSaving" type="text"></label>
      <label>内容<textarea v-model="newPrompt.content" :disabled="isSaving" rows="5" /></label>
      <button type="button" :disabled="isSaving" @click="createPrompt">
        <Check :size="15" aria-hidden="true" />创建
      </button>
    </section>

    <div v-if="configuration" class="chat-prompt-sidebar__list" role="list">
      <article v-for="prompt in configuration.prompts" :key="prompt.id" class="chat-prompt-sidebar__item" role="listitem">
        <button
          class="chat-prompt-sidebar__summary"
          type="button"
          :aria-expanded="isExpanded(prompt.id)"
          @click="togglePrompt(prompt.id)"
        >
          <ChevronDown v-if="isExpanded(prompt.id)" :size="16" aria-hidden="true" />
          <ChevronRight v-else :size="16" aria-hidden="true" />
          <span><strong>{{ prompt.label }}</strong><small>{{ prompt.isDefault ? "默认提示词" : "自定义提示词" }}</small></span>
          <mark v-if="prompt.id === selectedPromptId">使用中</mark>
        </button>

        <div v-if="isExpanded(prompt.id) && drafts[prompt.id]" class="chat-prompt-sidebar__editor">
          <label>名称<input :value="drafts[prompt.id]?.label ?? ''" :disabled="isSaving" type="text" @input="updateDraftLabel(prompt.id, $event)"></label>
          <label>内容<textarea :value="drafts[prompt.id]?.content ?? ''" :disabled="isSaving" rows="6" @input="updateDraftContent(prompt.id, $event)" /></label>
          <div class="chat-prompt-sidebar__actions">
            <button type="button" title="使用提示词" :disabled="isSaving" @click="usePrompt(prompt.id)">
              <Check :size="15" aria-hidden="true" />使用
            </button>
            <button type="button" :disabled="isSaving" @click="updatePrompt(prompt.id)">
              <Pencil :size="15" aria-hidden="true" />保存
            </button>
            <button class="is-danger" type="button" :disabled="isSaving" @click="emit('deletePrompt', prompt.id)">
              <Trash2 :size="15" aria-hidden="true" />删除
            </button>
          </div>
        </div>
      </article>
    </div>
  </aside>
</template>

<style scoped>
.chat-prompt-sidebar { background: var(--surface-raised); border-left: 1px solid var(--line); display: grid; gap: 0.8rem; grid-auto-rows: max-content; min-width: 0; overflow: auto; padding: 1rem; }
.chat-prompt-sidebar__header { align-items: center; display: flex; gap: 0.8rem; justify-content: space-between; }
.chat-prompt-sidebar__header p { color: var(--text-primary); font-size: 0.86rem; font-weight: 760; margin: 0; }
.chat-prompt-sidebar__header h3 { color: var(--text-tertiary); font-size: 0.72rem; font-weight: 650; margin: 0.22rem 0 0; }
.chat-prompt-sidebar__header button { align-items: center; border: 1px solid var(--line-strong); border-radius: 0.5rem; display: inline-flex; height: 2.3rem; justify-content: center; transition: background var(--transition-fast), border-color var(--transition-fast); width: 2.3rem; }
.chat-prompt-sidebar__header button:hover { background: var(--surface-hover); border-color: var(--accent-border); }
.chat-prompt-sidebar__notice { background: var(--danger-soft); border: 1px solid var(--status-danger-border); border-radius: 0.5rem; color: var(--status-danger-text); font-size: 0.76rem; line-height: 1.5; margin: 0; padding: 0.55rem 0.65rem; }
.chat-prompt-sidebar__empty { color: var(--text-tertiary); font-size: 0.78rem; margin: 0; }
.chat-prompt-sidebar__creator, .chat-prompt-sidebar__editor { border: 1px solid var(--line); border-radius: 0.5rem; display: grid; gap: 0.6rem; padding: 0.65rem; }
.chat-prompt-sidebar__list { display: grid; gap: 0.55rem; }
.chat-prompt-sidebar__item { border: 1px solid var(--line); border-radius: 0.5rem; overflow: hidden; }
.chat-prompt-sidebar__summary { align-items: center; display: grid; gap: 0.45rem; grid-template-columns: auto minmax(0, 1fr) auto; min-height: 2.8rem; padding: 0.55rem 0.65rem; text-align: left; width: 100%; }
.chat-prompt-sidebar__summary:hover { background: var(--surface-hover); }
.chat-prompt-sidebar__summary span { display: grid; gap: 0.1rem; min-width: 0; }
.chat-prompt-sidebar__summary strong { color: var(--text-primary); font-size: 0.78rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chat-prompt-sidebar__summary small { color: var(--text-tertiary); font-size: 0.68rem; }
.chat-prompt-sidebar__summary mark { background: var(--accent-soft); border: 1px solid var(--accent-border); border-radius: 999px; color: var(--accent-strong); font-size: 0.66rem; font-weight: 750; padding: 0.18rem 0.42rem; }
label { color: var(--text-secondary); display: grid; font-size: 0.72rem; font-weight: 700; gap: 0.3rem; }
input, textarea { background: var(--surface-raised); border: 1px solid var(--line-strong); border-radius: 0.45rem; color: var(--text-primary); min-height: 2.3rem; padding: 0.5rem 0.55rem; width: 100%; }
textarea { line-height: 1.5; resize: vertical; }
.chat-prompt-sidebar__actions { display: flex; flex-wrap: wrap; gap: 0.45rem; }
.chat-prompt-sidebar__actions button, .chat-prompt-sidebar__creator button { align-items: center; background: var(--accent); border-radius: 0.45rem; color: white; display: inline-flex; font-size: 0.75rem; font-weight: 750; gap: 0.35rem; min-height: 2.25rem; padding: 0 0.68rem; }
.chat-prompt-sidebar__actions button:nth-child(2) { background: var(--text-primary); }
.chat-prompt-sidebar__actions button.is-danger { background: var(--danger); }
button:disabled, input:disabled, textarea:disabled { cursor: not-allowed; opacity: 0.55; }
@media (max-width: 1120px) { .chat-prompt-sidebar { border-left: 0; border-top: 1px solid var(--line); max-height: none; } }
</style>
