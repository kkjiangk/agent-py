<script setup lang="ts">
import { MessageSquare, Plus, Trash2 } from "lucide-vue-next";

import type { ChatSessionSummary } from "@agent-py/api-contracts";

defineEmits<{
  create: [];
  delete: [sessionId: string];
  select: [sessionId: string];
}>();

withDefaults(defineProps<{
  readonly activeSessionId: string | null;
  readonly sessions: readonly ChatSessionSummary[];
  readonly variant?: "panel" | "rail";
}>(), {
  variant: "panel"
});

function sessionDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(new Date(value));
}
</script>

<template>
  <aside class="chat-session-list" :class="`chat-session-list--${variant}`" aria-label="对话历史">
    <div class="chat-session-list__header">
      <p>历史对话</p>
      <button type="button" title="新建对话" aria-label="新建对话" @click="$emit('create')">
        <Plus :size="17" aria-hidden="true" />
      </button>
    </div>
    <p v-if="sessions.length === 0" class="chat-session-list__empty">还没有对话，开始问一个问题吧。</p>
    <ul v-else>
      <li v-for="session in sessions" :key="session.id">
        <button
          type="button"
          class="chat-session-list__select"
          :class="{ 'chat-session-list__select--active': session.id === activeSessionId }"
          :aria-current="session.id === activeSessionId ? 'page' : undefined"
          @click="$emit('select', session.id)"
        >
          <MessageSquare :size="15" aria-hidden="true" />
          <span><strong>{{ session.title }}</strong><small>{{ sessionDate(session.updatedAt) }}</small></span>
        </button>
        <button type="button" class="chat-session-list__delete" :title="`删除 ${session.title}`" :aria-label="`删除 ${session.title}`" @click="$emit('delete', session.id)">
          <Trash2 :size="15" aria-hidden="true" />
        </button>
      </li>
    </ul>
  </aside>
</template>

<style scoped>
.chat-session-list { background: #fbfbfc; border-right: 1px solid var(--line); display: flex; flex-direction: column; min-height: 0; min-width: 0; overflow-y: auto; }
.chat-session-list__header { align-items: center; border-bottom: 1px solid var(--line); display: flex; justify-content: space-between; min-height: 3.75rem; padding: 0 0.85rem; }
.chat-session-list__header p { color: var(--text-secondary); font-size: 0.76rem; font-weight: 700; margin: 0; }
.chat-session-list__header button, .chat-session-list__delete { align-items: center; border-radius: 0.45rem; color: var(--text-secondary); display: inline-flex; height: 2rem; justify-content: center; width: 2rem; }
.chat-session-list__header button:hover, .chat-session-list__delete:hover { background: var(--surface-hover); color: var(--danger); }
.chat-session-list__empty { color: var(--text-tertiary); font-size: 0.82rem; line-height: 1.6; margin: 1rem; }
ul { list-style: none; margin: 0; padding: 0.45rem; }
li { align-items: center; display: grid; gap: 0.1rem; grid-template-columns: minmax(0, 1fr) auto; }
.chat-session-list__select { align-items: center; border-radius: 0.5rem; color: var(--text-secondary); display: flex; gap: 0.55rem; min-height: 3.25rem; min-width: 0; padding: 0.45rem 0.55rem; text-align: left; }
.chat-session-list__select:hover { background: var(--surface-hover); color: var(--text-primary); }
.chat-session-list__select--active { background: var(--surface-selected); color: var(--accent-strong); }
.chat-session-list__select > span { display: grid; min-width: 0; }
strong, small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
strong { font-size: 0.8rem; font-weight: 620; }
small { color: var(--text-tertiary); font-size: 0.68rem; margin-top: 0.15rem; }
.chat-session-list__delete { color: var(--text-tertiary); opacity: 0; }
li:hover .chat-session-list__delete, .chat-session-list__select--active + .chat-session-list__delete { opacity: 1; }
.chat-session-list--rail { background: transparent; border: 0; max-height: clamp(12rem, 38vh, 24rem); margin: 0.25rem 0 0.55rem; }
.chat-session-list--rail .chat-session-list__header { border-color: rgb(255 255 255 / 9%); min-height: 2.65rem; padding: 0 0.55rem; }
.chat-session-list--rail .chat-session-list__header p { color: var(--rail-muted); font-size: 0.7rem; }
.chat-session-list--rail .chat-session-list__header button, .chat-session-list--rail .chat-session-list__delete { color: var(--rail-muted); }
.chat-session-list--rail .chat-session-list__header button:hover, .chat-session-list--rail .chat-session-list__delete:hover { background: var(--rail-hover); color: #fff; }
.chat-session-list--rail .chat-session-list__empty { color: var(--rail-muted); font-size: 0.74rem; margin: 0.65rem 0.55rem; }
.chat-session-list--rail ul { padding: 0.3rem 0.15rem; }
.chat-session-list--rail li { gap: 0; }
.chat-session-list--rail .chat-session-list__select { color: var(--rail-muted); min-height: 2.75rem; padding: 0.38rem 0.5rem; }
.chat-session-list--rail .chat-session-list__select:hover { background: var(--rail-hover); color: var(--rail-text); }
.chat-session-list--rail .chat-session-list__select--active { background: #343538; color: #fff; }
.chat-session-list--rail .chat-session-list__select--active svg { color: #65d6b3; }
.chat-session-list--rail strong { color: inherit; font-size: 0.76rem; }
.chat-session-list--rail small { color: var(--rail-muted); }
@media (max-width: 860px) { .chat-session-list { border-bottom: 1px solid var(--line); border-right: 0; max-height: 13rem; overflow-y: auto; } }
</style>
