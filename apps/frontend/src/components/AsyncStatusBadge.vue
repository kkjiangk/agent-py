<script setup lang="ts">
import { CircleAlert, CircleCheck, Clock3, LoaderCircle } from "lucide-vue-next";
import { computed } from "vue";

import { describeAsyncStatus } from "../ui/asyncStatus";

const props = defineProps<{
  readonly status: string | null | undefined;
  readonly detail?: string;
  readonly compact?: boolean;
}>();

const description = computed(() => describeAsyncStatus(props.status));
const icon = computed(() => {
  if (description.value.tone === "success") return CircleCheck;
  if (description.value.tone === "danger") return CircleAlert;
  if (description.value.active) return LoaderCircle;
  return Clock3;
});
</script>

<template>
  <span
    class="async-status-badge"
    :class="{ 'async-status-badge--compact': compact, 'async-status-badge--active': description.active }"
    :data-tone="description.tone"
    role="status"
    aria-live="polite"
  >
    <component :is="icon" :size="compact ? 13 : 15" aria-hidden="true" />
    <span>{{ description.label }}</span>
    <small v-if="detail && !compact">{{ detail }}</small>
  </span>
</template>

<style scoped>
.async-status-badge { align-items: center; background: var(--status-neutral-bg); border: 1px solid var(--status-neutral-border); border-radius: 999px; color: var(--status-neutral-text); display: inline-flex; font-size: 0.75rem; font-weight: 650; gap: 0.35rem; line-height: 1; max-width: 100%; min-height: 1.85rem; padding: 0.3rem 0.55rem; white-space: nowrap; }
.async-status-badge small { color: inherit; font-size: 0.72rem; font-weight: 500; opacity: 0.82; overflow: hidden; text-overflow: ellipsis; }
.async-status-badge[data-tone="waiting"] { background: var(--status-waiting-bg); border-color: var(--status-waiting-border); color: var(--status-waiting-text); }
.async-status-badge[data-tone="running"] { background: var(--status-running-bg); border-color: var(--status-running-border); color: var(--status-running-text); }
.async-status-badge[data-tone="success"] { background: var(--status-success-bg); border-color: var(--status-success-border); color: var(--status-success-text); }
.async-status-badge[data-tone="danger"] { background: var(--status-danger-bg); border-color: var(--status-danger-border); color: var(--status-danger-text); }
.async-status-badge--active svg { animation: async-status-spin 0.9s linear infinite; }
.async-status-badge--compact { min-height: 1.6rem; padding: 0.22rem 0.42rem; }
@keyframes async-status-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .async-status-badge--active svg { animation: none; } }
</style>
