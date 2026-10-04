<script setup lang="ts">
import { BookOpenCheck, FolderOpen } from "lucide-vue-next";

import type { AiopsDiagnosticCase } from "@agent-py/api-contracts";

defineEmits<{ select: [taskId: string]; "open-document": [documentId: string] }>();
defineProps<{ readonly cases: readonly AiopsDiagnosticCase[] }>();

function caseSummary(summary: string): string {
  const plainText = summary
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/[`*_>|-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return plainText.length > 180 ? `${plainText.slice(0, 177)}...` : plainText;
}
</script>

<template>
  <section class="aiops-case-library" aria-label="诊断案例库">
    <header><div><p>案例库</p><h3>已归档的诊断案例</h3></div><BookOpenCheck :size="17" aria-hidden="true" /></header>
    <p v-if="cases.length === 0">已完成的诊断会自动保存到这里。</p>
    <ul v-else><li v-for="item in cases" :key="item.id"><button class="aiops-case-library__case" type="button" @click="$emit('select', item.taskId)"><strong>{{ item.alertName || item.service || '诊断案例' }}</strong><small>{{ item.service || '未提供服务名称' }} · {{ item.keywords.join(', ') || '未提取关键词' }}</small><span>{{ caseSummary(item.summary) }}</span></button><button class="aiops-case-library__document" type="button" title="打开生成的知识文档" :aria-label="`打开 ${item.alertName || item.service || '诊断案例'} 生成的知识文档`" @click="$emit('open-document', item.documentId)"><FolderOpen :size="16" aria-hidden="true" /></button></li></ul>
  </section>
</template>

<style scoped>
.aiops-case-library { border-top: 1px solid var(--line); padding: 1rem 1.2rem; }
header { align-items: center; display: flex; justify-content: space-between; }
header p { color: var(--text-tertiary); font-size: 0.7rem; font-weight: 700; margin: 0 0 0.25rem; }
h3 { font-size: 0.9rem; font-weight: 680; margin: 0; }
.aiops-case-library > p { color: var(--text-tertiary); font-size: 0.8rem; margin: 0.8rem 0 0; }
ul { display: grid; gap: 0.35rem; list-style: none; margin: 0.8rem 0 0; padding: 0; }
li { align-items: center; display: grid; gap: 0.45rem; grid-template-columns: minmax(0, 1fr) 2rem; }
.aiops-case-library__case { display: grid; gap: 0.2rem; min-width: 0; padding: 0.55rem 0; text-align: left; width: 100%; }
.aiops-case-library__case:hover strong { color: var(--accent-strong); text-decoration: underline; }
.aiops-case-library__document { align-items: center; border: 1px solid transparent; color: var(--text-secondary); display: inline-flex; height: 2rem; justify-content: center; width: 2rem; }
.aiops-case-library__document:hover { background: var(--surface-hover); border-color: var(--line); color: var(--accent-strong); }
strong { font-size: 0.8rem; font-weight: 680; }
small, span { color: var(--text-tertiary); font-size: 0.72rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
span { color: var(--text-secondary); }
</style>
