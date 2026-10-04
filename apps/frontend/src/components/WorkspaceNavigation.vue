<script setup lang="ts">
import { Activity, BookOpen, Cable, MessageSquare } from "lucide-vue-next";

defineProps<{ readonly activePath: string }>();

const entries = [
  { icon: MessageSquare, label: "对话", to: "/chat" },
  { icon: BookOpen, label: "知识库", to: "/knowledge" },
  { icon: Activity, label: "智能诊断", to: "/aiops" },
  { icon: Cable, label: "MCP 连接", to: "/mcp" }
] as const;
</script>

<template>
  <nav class="workspace-navigation" aria-label="工作区导航">
    <template v-for="entry in entries" :key="entry.to">
      <RouterLink
        :to="entry.to"
        class="workspace-navigation__link"
        :class="{ 'workspace-navigation__link--active': activePath === entry.to }"
        :aria-current="activePath === entry.to ? 'page' : undefined"
      >
        <component :is="entry.icon" :size="18" stroke-width="1.8" aria-hidden="true" />
        <span>{{ entry.label }}</span>
      </RouterLink>
      <slot v-if="entry.to === '/chat' && activePath === '/chat'" name="chat-history" />
    </template>
  </nav>
</template>

<style scoped>
.workspace-navigation { display: grid; gap: 0.2rem; }
.workspace-navigation__link { align-items: center; border-radius: var(--radius-sm); color: var(--rail-muted); display: flex; font-size: 0.9rem; font-weight: 560; gap: 0.72rem; min-height: 2.7rem; padding: 0 0.7rem; text-decoration: none; transition: background var(--transition-fast), color var(--transition-fast); }
.workspace-navigation__link:hover { background: var(--rail-hover); color: var(--rail-text); }
.workspace-navigation__link--active { background: #343538; color: #ffffff; font-weight: 650; }
.workspace-navigation__link--active svg { color: #65d6b3; }
</style>
