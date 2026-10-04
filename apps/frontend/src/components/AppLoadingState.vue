<script setup lang="ts">
defineProps<{ readonly label: string }>();
</script>

<template>
  <div class="loading-state" role="status" aria-live="polite">
    <span class="loading-state__indicator" aria-hidden="true" />
    <span>{{ label }}</span>
  </div>
</template>

<style scoped>
.loading-state {
  align-items: center;
  color: var(--text-secondary);
  display: inline-flex;
  font-size: 0.9rem;
  gap: 0.65rem;
  min-height: 2.5rem;
}

.loading-state__indicator {
  animation: spin 0.8s linear infinite;
  border: 2px solid var(--line-strong);
  border-right-color: var(--accent);
  border-radius: 50%;
  display: block;
  height: 1rem;
  width: 1rem;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
