<script setup lang="ts">
import { ExternalLink, FileText, X } from "lucide-vue-next";

import type { ReferenceSourceSseEvent } from "@agent-py/api-contracts";
import RetrievalStageTrace from "./RetrievalStageTrace.vue";
import UserFeedbackControl from "./UserFeedbackControl.vue";

type ChatReference = ReferenceSourceSseEvent["reference"];

const emit = defineEmits<{ close: []; "open-document": [reference: ChatReference] }>();
const props = defineProps<{ readonly messageId: string; readonly reference: ChatReference }>();

function sourceTypeLabel(): string {
  if (props.reference.knowledgeType === "sop") return "SOP";
  if (props.reference.knowledgeType === "diagnostic-case") return "故障案例";
  if (props.reference.knowledgeType === "document") return "知识库文档";
  return props.reference.sourceType;
}

function metadataValue(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}
</script>

<template>
  <aside class="chat-citation-detail" aria-label="来源详情">
    <header><div><p>来源详情</p><h2>{{ reference.title }}</h2></div><button type="button" aria-label="关闭来源详情" title="关闭来源详情" @click="emit('close')"><X :size="16" aria-hidden="true" /></button></header>
    <dl class="chat-citation-detail__summary"><div><dt>类型</dt><dd>{{ sourceTypeLabel() }}</dd></div><div v-if="reference.rrfScore !== undefined"><dt>RRF 融合分</dt><dd>{{ reference.rrfScore.toFixed(4) }}</dd></div></dl>
    <section><p>检索阶段</p><RetrievalStageTrace :reference="reference" /></section>
    <section><p>引用反馈</p><UserFeedbackControl target-type="citation" :target-id="messageId" :subject-id="reference.id" /></section>
    <section v-if="reference.excerpt"><p>内容摘录</p><blockquote>{{ reference.excerpt }}</blockquote></section>
    <section v-if="reference.metadata && Object.keys(reference.metadata).length"><p>元数据</p><dl class="chat-citation-detail__metadata"><div v-for="(value, key) in reference.metadata" :key="key"><dt>{{ key }}</dt><dd>{{ metadataValue(value) }}</dd></div></dl></section>
    <button v-if="reference.documentId && reference.knowledgeBaseId" type="button" :aria-label="`在知识库中打开 ${reference.title}`" @click="emit('open-document', reference)"><FileText :size="15" aria-hidden="true" />在知识库中打开<ExternalLink :size="13" aria-hidden="true" /></button>
  </aside>
</template>

<style scoped>
.chat-citation-detail { background: #fbfbfc; border: 1px solid var(--line); border-radius: var(--radius-md); display: grid; gap: 0.85rem; max-width: 46rem; padding: 1rem; }
header { align-items: start; display: flex; gap: 1rem; justify-content: space-between; }
header p, section > p { color: var(--text-tertiary); font-size: 0.7rem; font-weight: 700; margin: 0 0 0.3rem; }
h2 { font-size: 0.92rem; font-weight: 680; margin: 0; overflow-wrap: anywhere; }
header button { align-items: center; border-radius: 0.45rem; color: var(--text-secondary); display: inline-flex; height: 2rem; justify-content: center; width: 2rem; }
header button:hover, .chat-citation-detail > button:hover { background: var(--surface-hover); }
.chat-citation-detail__summary { display: flex; flex-wrap: wrap; gap: 1rem; margin: 0; }
dt { color: var(--text-tertiary); font-size: 0.66rem; font-weight: 700; }
dd { color: var(--text-secondary); font-size: 0.78rem; margin: 0.2rem 0 0; overflow-wrap: anywhere; }
blockquote { border-left: 2px solid var(--accent-border); color: var(--text-secondary); font-size: 0.82rem; line-height: 1.6; margin: 0; padding-left: 0.7rem; }
.chat-citation-detail__metadata { display: grid; gap: 0.5rem; grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr)); }
.chat-citation-detail > button { align-items: center; background: var(--accent-soft); border: 1px solid var(--accent-border); border-radius: 0.45rem; color: var(--accent-strong); display: inline-flex; font-size: 0.78rem; font-weight: 700; gap: 0.35rem; justify-self: start; min-height: 2.15rem; padding: 0 0.65rem; }
</style>
