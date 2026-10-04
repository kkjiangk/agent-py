<script setup lang="ts">
import AppEmptyState from "../components/AppEmptyState.vue";

defineProps<{
  readonly description: string;
  readonly eyebrow: string;
  readonly title: string;
}>();
</script>

<template>
  <section class="placeholder-view" :aria-labelledby="`${title}-heading`">
    <p>{{ eyebrow }}</p>
    <h2 :id="`${title}-heading`">{{ title }}</h2>
    <AppEmptyState :title="description" />
  </section>
</template>

<style scoped>
.placeholder-view > p { color: var(--text-tertiary); font-size: 0.78rem; font-weight: 650; margin: 0 0 0.6rem; text-transform: uppercase; }
.placeholder-view > h2 { font-size: clamp(1.75rem, 3vw, 2.6rem); font-weight: 680; margin: 0 0 2.25rem; }
</style>
