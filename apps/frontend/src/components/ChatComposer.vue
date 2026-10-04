<script setup lang="ts">
import { ArrowUp, BrainCircuit, LoaderCircle } from "lucide-vue-next";
import { computed, ref, watch } from "vue";

import type { ChatMemoryMode, ChatMemoryState } from "@agent-py/api-contracts";

const emit = defineEmits<{
  send: [content: string];
  applyMemory: [mode: ChatMemoryMode];
  compactMemory: [];
}>();
const props = defineProps<{
  readonly disabled: boolean;
  readonly isSending: boolean;
  readonly isUpdatingMemory: boolean;
  readonly memory: ChatMemoryState | null;
}>();
const content = ref("");
const selectedMode = ref<ChatMemoryMode>(props.memory?.mode ?? "every_30_turns");
const isHardLimited = computed(() => (props.memory?.contextUsagePercent ?? 0) >= 95);
const inputDisabled = computed(() => props.disabled || props.isSending || isHardLimited.value);

watch(
  () => props.memory?.mode,
  (mode) => {
    if (mode !== undefined) selectedMode.value = mode;
  }
);

function submit(): void {
  const nextContent = content.value.trim();
  if (nextContent.length === 0 || inputDisabled.value) return;
  emit("send", nextContent);
  content.value = "";
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  submit();
}
</script>

<template>
  <form class="chat-composer" @submit.prevent="submit">
    <label class="chat-composer__label" for="chat-message">输入问题</label>
    <div class="chat-composer__row">
      <div class="chat-composer__field">
        <textarea id="chat-message" v-model="content" rows="1" placeholder="向 Super AI 描述你正在处理的问题" :disabled="inputDisabled" @keydown="handleKeydown" />
        <button type="submit" title="发送消息" aria-label="发送消息" :disabled="inputDisabled || !content.trim()"><LoaderCircle v-if="isSending" class="chat-composer__spin" :size="18" aria-hidden="true" /><ArrowUp v-else :size="18" aria-hidden="true" /></button>
      </div>
      <aside class="chat-composer__memory" aria-label="会话记忆设置">
        <div class="chat-composer__memory-head">
          <span><BrainCircuit :size="15" aria-hidden="true" />上下文</span>
          <strong>{{ memory?.contextUsagePercent ?? 0 }}%</strong>
        </div>
        <progress :value="memory?.contextUsagePercent ?? 0" max="100" aria-label="上下文窗口占用" />
        <div class="chat-composer__memory-actions">
          <select v-model="selectedMode" aria-label="记忆模式" :disabled="!memory || isUpdatingMemory">
            <option value="every_30_turns">每 30 轮压缩</option>
            <option value="context_70_percent">占用 70% 自动压缩</option>
            <option value="manual">手动压缩</option>
          </select>
          <button
            v-if="memory?.mode === 'manual' && selectedMode === 'manual'"
            class="chat-composer__apply"
            type="button"
            :disabled="isUpdatingMemory"
            @click="emit('compactMemory')"
          >{{ isUpdatingMemory ? "压缩中" : "立即压缩" }}</button>
          <button
            v-else
            class="chat-composer__apply"
            type="button"
            :disabled="!memory || isUpdatingMemory || selectedMode === memory?.mode"
            @click="emit('applyMemory', selectedMode)"
          >{{ isUpdatingMemory ? "应用中" : "应用" }}</button>
        </div>
      </aside>
    </div>
    <span class="chat-composer__hint">Enter 发送，Shift+Enter 换行</span>
    <span v-if="isSending" class="chat-composer__status" role="status" aria-live="polite">正在生成回答，请稍候</span>
    <span v-else-if="isHardLimited" class="chat-composer__limit" role="alert">上下文已达到 95%，请执行手动压缩</span>
  </form>
</template>

<style scoped>
.chat-composer { background: linear-gradient(to top, var(--surface-raised) 68%, rgb(255 255 255 / 0%)); display: grid; gap: 0.45rem; padding: 1.5rem clamp(1rem, 4vw, 4.5rem) 1.25rem; }
.chat-composer__label { color: var(--text-tertiary); font-size: 0.72rem; font-weight: 650; }
.chat-composer__row { align-items: stretch; display: grid; gap: 0.75rem; grid-template-columns: minmax(0, 1fr) 17rem; }
.chat-composer__field { background: var(--surface-raised); border: 1px solid var(--line-strong); border-radius: 1.25rem; box-shadow: 0 6px 20px rgb(0 0 0 / 6%); display: grid; grid-template-columns: minmax(0, 1fr) auto; padding: 0.35rem; transition: border-color var(--transition-fast), box-shadow var(--transition-fast); }
textarea { background: transparent; border: 0; color: var(--text-primary); line-height: 1.55; min-height: 2.8rem; outline: 0; overflow-y: auto; padding: 0.62rem 0.55rem 0.5rem 0.75rem; resize: none; width: 100%; }
textarea::placeholder { color: var(--text-tertiary); }
.chat-composer__field button { align-self: end; align-items: center; background: var(--text-primary); border-radius: 50%; color: #fff; display: inline-flex; height: 2.35rem; justify-content: center; margin: 0 0.15rem 0.15rem 0; transition: background var(--transition-fast), transform var(--transition-fast); width: 2.35rem; }
.chat-composer__field button:hover:not(:disabled) { background: var(--accent-strong); transform: translateY(-1px); }
.chat-composer__field button:disabled { background: #d7d7da; color: #fff; }
.chat-composer__memory { border-left: 1px solid var(--line); display: grid; gap: 0.4rem; padding: 0.2rem 0 0.2rem 0.75rem; }
.chat-composer__memory-head { align-items: center; display: flex; justify-content: space-between; }
.chat-composer__memory-head span { align-items: center; color: var(--text-secondary); display: inline-flex; font-size: 0.72rem; gap: 0.35rem; }
.chat-composer__memory-head strong { font-size: 0.78rem; font-variant-numeric: tabular-nums; }
progress { accent-color: var(--text-primary); height: 0.35rem; width: 100%; }
.chat-composer__memory-actions { display: grid; gap: 0.4rem; grid-template-columns: minmax(0, 1fr) auto; }
select { background: var(--surface-subtle); border: 1px solid var(--line); border-radius: 0.35rem; color: var(--text-primary); font-size: 0.7rem; min-width: 0; padding: 0.35rem; }
.chat-composer__apply { background: var(--surface-subtle); border: 1px solid var(--line-strong); border-radius: 0.35rem; color: var(--text-primary); font-size: 0.7rem; padding: 0.35rem 0.55rem; white-space: nowrap; }
.chat-composer__apply:disabled { color: var(--text-tertiary); }
.chat-composer__status { color: var(--status-running-text); font-size: 0.75rem; font-weight: 600; padding-left: 0.75rem; }
.chat-composer__limit { color: var(--status-error-text); font-size: 0.75rem; font-weight: 600; padding-left: 0.75rem; }
.chat-composer__hint { color: var(--text-tertiary); font-size: 0.7rem; padding-left: 0.75rem; }
.chat-composer__spin { animation: chat-composer-spin 0.8s linear infinite; }
@keyframes chat-composer-spin { to { transform: rotate(360deg); } }
@media (max-width: 760px) { .chat-composer { padding: 1rem 0 0; } .chat-composer__row { grid-template-columns: minmax(0, 1fr); } .chat-composer__memory { border-left: 0; border-top: 1px solid var(--line); padding: 0.6rem 0 0; } }
</style>
