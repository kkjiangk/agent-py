<script setup lang="ts">
import { BookOpen, CircleAlert, ClipboardList, FileText, LoaderCircle, Wrench } from "lucide-vue-next";

import type { SseEvent } from "@agent-py/api-contracts";

import AsyncStatusBadge from "./AsyncStatusBadge.vue";

defineProps<{ readonly events: readonly SseEvent[]; readonly isRunning: boolean }>();

function eventLabel(event: SseEvent): string {
  if (event.type === "task.status") return event.task.message ?? event.task.status;
  if (event.type === "tool.call") return event.toolCall.name;
  if (event.type === "reference.source") return event.reference.title;
  if (event.type === "report") return event.report.title;
  if (event.type === "error") return event.error.message;
  return "诊断流程已完成";
}

function eventStatus(event: SseEvent): string | null {
  if (event.type === "task.status") return event.task.status;
  if (event.type === "tool.call") return event.toolCall.status;
  return null;
}

function eventIcon(event: SseEvent): typeof LoaderCircle {
  if (event.type === "tool.call") return Wrench;
  if (event.type === "reference.source") return BookOpen;
  if (event.type === "report") return FileText;
  if (event.type === "error") return CircleAlert;
  if (event.type === "complete") return ClipboardList;
  return LoaderCircle;
}

</script>

<template>
  <section class="aiops-timeline" aria-label="诊断过程">
    <header><div><p>诊断过程</p><h3>规划、执行、重规划与报告</h3></div><AsyncStatusBadge v-if="isRunning" status="running" compact /></header>
    <p v-if="events.length === 0" class="aiops-timeline__empty">发起诊断后，这里会按真实事件展示检索、工具调用、重规划和报告。</p>
    <ol v-else>
      <li v-for="event in events" :key="event.id" :class="`aiops-timeline__event--${event.type.replace('.', '-')}`"><component :is="eventIcon(event)" :size="16" aria-hidden="true" /><div><div class="aiops-timeline__event-header"><strong>{{ eventLabel(event) }}</strong><AsyncStatusBadge v-if="eventStatus(event)" :status="eventStatus(event)" compact /></div><small>{{ new Date(event.timestamp).toLocaleTimeString('zh-CN') }}</small><span v-if="event.type === 'task.status' && event.task.progress !== undefined" class="aiops-timeline__progress"><i :style="{ width: `${event.task.progress}%` }" /></span><small v-if="event.type === 'report'">报告正文已沉淀到上方最终诊断报告。</small></div></li>
    </ol>
  </section>
</template>

<style scoped>
.aiops-timeline { border-bottom: 1px solid var(--line); min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 1.2rem; }
header { align-items: center; display: flex; justify-content: space-between; }
header p { color: var(--text-tertiary); font-size: 0.7rem; font-weight: 700; margin: 0 0 0.3rem; }
h3 { font-size: 0.95rem; font-weight: 680; margin: 0; }
.aiops-timeline__empty { color: var(--text-tertiary); font-size: 0.84rem; margin: 1rem 0 0; }
ol { display: grid; gap: 0.8rem; list-style: none; margin: 1rem 0 0; padding: 0; }
li { align-items: start; display: grid; gap: 0.55rem; grid-template-columns: auto minmax(0, 1fr); }
li > svg { color: var(--accent-strong); margin-top: 0.1rem; }
li > div { display: grid; gap: 0.22rem; min-width: 0; }
.aiops-timeline__event-header { align-items: center; display: flex; flex-wrap: wrap; gap: 0.45rem; justify-content: space-between; }
strong { font-size: 0.82rem; font-weight: 650; overflow-wrap: anywhere; }
small { color: var(--text-tertiary); font-size: 0.72rem; overflow-wrap: anywhere; }
.aiops-timeline__event--error > svg, .aiops-timeline__event--error strong { color: var(--danger); }
.aiops-timeline__progress { background: var(--line); display: block; height: 0.2rem; margin-top: 0.25rem; max-width: 16rem; }
.aiops-timeline__progress i { background: var(--accent); display: block; height: 100%; }
</style>
