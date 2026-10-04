<script setup lang="ts">
withDefaults(
  defineProps<{
    readonly detail?: string;
    readonly title: string;
  }>(),
  { detail: "" }
);
</script>

<template>
  <section class="empty-state" aria-live="polite">
    <span class="empty-state__mark" aria-hidden="true" />
    <h2>{{ title }}</h2>
    <p v-if="detail">{{ detail }}</p>
  </section>
</template>

<style scoped>
.empty-state {
  align-items: flex-start;
  border-top: 1px solid var(--line);
  display: grid;
  gap: 0.65rem;
  max-width: 42rem;
  padding: 2rem 0;
}

.empty-state__mark {
  background: var(--accent-soft);
  border: 1px solid var(--accent-border);
  display: block;
  height: 0.7rem;
  width: 2.4rem;
}

h2 {
  font-size: 1.05rem;
  font-weight: 650;
  margin: 0;
}

p { color: var(--text-secondary); margin: 0; }
</style>
