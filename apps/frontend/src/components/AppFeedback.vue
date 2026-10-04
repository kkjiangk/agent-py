<script setup lang="ts">
import { X } from "lucide-vue-next";
import { storeToRefs } from "pinia";
import { onBeforeUnmount, watch } from "vue";

import { useFeedbackStore } from "../stores/feedback";

const feedback = useFeedbackStore();
const { current } = storeToRefs(feedback);
const AUTO_DISMISS_MS = 3_000;
let dismissTimer: ReturnType<typeof setTimeout> | undefined;

function clearDismissTimer(): void {
  if (dismissTimer !== undefined) {
    clearTimeout(dismissTimer);
    dismissTimer = undefined;
  }
}

watch(current, (message) => {
  clearDismissTimer();
  if (message === null) return;
  const messageId = message.id;
  dismissTimer = setTimeout(() => {
    if (current.value?.id === messageId) feedback.dismiss();
  }, AUTO_DISMISS_MS);
}, { immediate: true });

onBeforeUnmount(clearDismissTimer);
</script>

<template>
  <Transition name="feedback">
    <aside v-if="current" :key="current.id" class="app-feedback" :class="`app-feedback--${current.kind}`" role="alert">
      <span>{{ current.message }}</span>
      <button type="button" title="关闭提示" aria-label="关闭提示" @click="feedback.dismiss">
        <X :size="17" aria-hidden="true" />
      </button>
    </aside>
  </Transition>
</template>

<style scoped>
.app-feedback { align-items: center; background: var(--surface-raised); border: 1px solid var(--line-strong); box-shadow: 0 12px 30px rgb(32 48 67 / 16%); display: flex; gap: 1rem; justify-content: space-between; left: 50%; max-width: min(32rem, calc(100vw - 2rem)); padding: 0.75rem 0.75rem 0.75rem 1rem; position: fixed; top: 1rem; transform: translateX(-50%); z-index: 20; }
.app-feedback--error { border-left: 3px solid var(--danger); }
button { color: inherit; }
.feedback-enter-active, .feedback-leave-active { transition: opacity 160ms ease, transform 160ms ease; }
.feedback-enter-from, .feedback-leave-to { opacity: 0; transform: translate(-50%, -0.5rem); }
</style>
