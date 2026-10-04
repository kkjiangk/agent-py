<script setup lang="ts">
import { AlertTriangle, RefreshCw, Stethoscope } from "lucide-vue-next";

import type { ActiveAlert } from "@agent-py/api-contracts";

import AppErrorState from "./AppErrorState.vue";
import AppLoadingState from "./AppLoadingState.vue";
import AsyncStatusBadge from "./AsyncStatusBadge.vue";

const emit = defineEmits<{ diagnose: [alert: ActiveAlert]; refresh: [] }>();
defineProps<{
  readonly alerts: readonly ActiveAlert[];
  readonly errorMessage: string | null;
  readonly isLoading: boolean;
}>();

function formatStart(value: string): string {
  if (value.length === 0) return "未提供开始时间";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function alertStatus(status: string): string {
  return status.toLowerCase() === "active" ? "active" : status;
}
</script>

<template>
  <section class="active-alert-list" aria-label="活跃外部告警">
    <header>
      <div><p>活跃告警</p><h2>外部告警订阅</h2></div>
      <button :disabled="isLoading" type="button" aria-label="刷新活跃告警" title="刷新活跃告警" @click="emit('refresh')"><RefreshCw :class="{ 'active-alert-list__refreshing': isLoading }" :size="16" aria-hidden="true" /></button>
    </header>
    <AppLoadingState v-if="isLoading" label="正在刷新活跃告警" />
    <AppErrorState v-else-if="errorMessage !== null" :can-retry="true" :message="errorMessage" @retry="emit('refresh')" />
    <p v-else-if="alerts.length === 0" class="active-alert-list__empty">当前告警源没有返回活跃告警。</p>
    <ul v-else>
      <li v-for="alert in alerts" :key="alert.id">
        <div class="active-alert-list__signal"><AlertTriangle :size="16" aria-hidden="true" /><div><strong>{{ alert.alertName }}</strong><p>{{ alert.summary }}</p></div></div>
        <dl><div><dt>服务</dt><dd>{{ alert.service }}</dd></div><div><dt>级别</dt><dd :class="`active-alert-list__severity--${alert.severity.toLowerCase()}`">{{ alert.severity }}</dd></div><div><dt>状态</dt><dd><AsyncStatusBadge :status="alertStatus(alert.status)" compact /></dd></div><div><dt>开始时间</dt><dd>{{ formatStart(alert.startsAt) }}</dd></div></dl>
        <button type="button" :aria-label="`诊断 ${alert.alertName}`" @click="emit('diagnose', alert)"><Stethoscope :size="15" aria-hidden="true" />诊断</button>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.active-alert-list { border-bottom: 1px solid var(--line); }
header { align-items: center; border-bottom: 1px solid var(--line); display: flex; justify-content: space-between; min-height: 3.8rem; padding: 0.8rem 1.2rem; }
header p { color: var(--text-tertiary); font-size: 0.7rem; font-weight: 700; margin: 0 0 0.2rem; }
h2 { font-size: 0.9rem; font-weight: 680; margin: 0; }
header button { align-items: center; border: 1px solid var(--line-strong); display: inline-flex; height: 2rem; justify-content: center; width: 2rem; }
header button:hover:not(:disabled) { background: var(--surface-hover); border-color: var(--accent-border); color: var(--accent-strong); }
header button:disabled { cursor: wait; opacity: 0.65; }
.active-alert-list__refreshing { animation: rotate 0.8s linear infinite; }
.loading-state, .error-state, .active-alert-list__empty { margin: 0.9rem 1.2rem; }
.active-alert-list__empty { color: var(--text-tertiary); font-size: 0.82rem; }
ul { list-style: none; margin: 0; max-height: 19rem; overflow-y: auto; padding: 0; }
li { align-items: start; border-top: 1px solid var(--line); display: grid; gap: 0.75rem; grid-template-columns: minmax(0, 1fr); padding: 0.85rem 1.2rem; }
.active-alert-list__signal { align-items: flex-start; color: var(--danger); display: flex; gap: 0.55rem; min-width: 0; }
.active-alert-list__signal > div { color: var(--text-primary); min-width: 0; }
strong { display: block; font-size: 0.82rem; font-weight: 700; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.active-alert-list__signal p { color: var(--text-secondary); font-size: 0.77rem; line-height: 1.4; margin: 0.2rem 0 0; }
dl { display: grid; gap: 0.6rem; grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 0; }
dt { color: var(--text-tertiary); font-size: 0.65rem; font-weight: 700; }
dd { color: var(--text-secondary); font-size: 0.75rem; margin: 0.2rem 0 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.active-alert-list__severity--critical, .active-alert-list__severity--high { color: var(--danger); font-weight: 700; }
.active-alert-list__severity--warning { color: #9a6700; font-weight: 700; }
li > button { align-items: center; border: 1px solid var(--accent-border); color: var(--accent-strong); display: inline-flex; font-size: 0.78rem; font-weight: 700; gap: 0.35rem; justify-self: start; min-height: 2rem; padding: 0 0.55rem; }
li > button:hover { background: var(--accent-soft); }
@keyframes rotate { to { transform: rotate(360deg); } }
@media (max-width: 520px) { header, li { padding-left: 0.9rem; padding-right: 0.9rem; } dl { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
