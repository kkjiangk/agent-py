<script setup lang="ts">
const emit = defineEmits<{ retry: [] }>();
withDefaults(
  defineProps<{
    readonly canRetry?: boolean;
    readonly message: string;
  }>(),
  { canRetry: false }
);
</script>

<template>
  <section class="error-state" role="alert">
    <span class="error-state__label">加载失败</span>
    <p>{{ message }}</p>
    <button v-if="canRetry" type="button" @click="emit('retry')">重试</button>
  </section>
</template>

<style scoped>
.error-state { border-left: 3px solid var(--danger); color: var(--text-primary); padding: 0.15rem 0 0.15rem 1rem; }
.error-state__label { color: var(--danger); font-size: 0.78rem; font-weight: 700; }
p { margin: 0.35rem 0 0; }
button { margin-top: 0.8rem; }
</style>
