<script setup lang="ts">
import type { DocumentChunkPreview, DocumentIndexTask, KnowledgeDocument } from "@agent-py/api-contracts";

import AsyncStatusBadge from "./AsyncStatusBadge.vue";

const props = defineProps<{
  readonly document: KnowledgeDocument;
  readonly task: DocumentIndexTask | undefined;
  readonly preview?: DocumentChunkPreview | null;
}>();

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function formatSize(bytes: number): string {
  return bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`;
}

function sourceLabel(): string {
  return props.document.source === "upload" ? "手动上传" : (props.document.source ?? "未知");
}
</script>

<template>
  <section class="knowledge-document-detail" aria-label="文档详情">
    <header><div><p>文档详情</p><h3>{{ document.filename }}</h3></div></header>
    <dl>
      <div><dt>文件类型</dt><dd>{{ document.mimeType }}</dd></div>
      <div><dt>文件大小</dt><dd>{{ formatSize(document.sizeBytes) }}</dd></div>
      <div><dt>上传时间</dt><dd>{{ formatDate(document.uploadedAt) }}</dd></div>
      <div><dt>文档状态</dt><dd><AsyncStatusBadge :status="document.status" compact /></dd></div>
      <div><dt>索引状态</dt><dd><AsyncStatusBadge :status="task?.status ?? document.indexStatus" compact /></dd></div>
      <div v-if="task?.failureReason"><dt>索引问题</dt><dd class="knowledge-document-detail__failure">{{ task.failureReason }}</dd></div>
      <div><dt>文件指纹</dt><dd class="knowledge-document-detail__hash">{{ document.contentHash }}</dd></div>
      <div><dt>来源</dt><dd>{{ sourceLabel() }}</dd></div>
      <div><dt>分片策略</dt><dd>{{ document.chunking?.strategy ?? "fixed-character" }}</dd></div>
    </dl>
    <section v-if="preview" class="knowledge-document-detail__preview" aria-label="分片预览">
      <header><div><p>分片预览</p><h4>共 {{ preview.totalChunks }} 个分片</h4></div></header>
      <ol><li v-for="item in preview.items" :key="item.index"><strong>分片 {{ item.index + 1 }} · {{ item.characterCount }} 字</strong><p>{{ item.excerpt }}</p></li></ol>
    </section>
  </section>
</template>

<style scoped>
.knowledge-document-detail { max-height: clamp(18rem, 58dvh, 38rem); min-width: 0; overflow-y: auto; overscroll-behavior: contain; padding: 1rem 1.15rem 1.2rem; scrollbar-gutter: stable; }
header { align-items: start; display: flex; gap: 0.75rem; justify-content: space-between; }
p { color: var(--text-tertiary); font-size: 0.7rem; font-weight: 700; margin: 0 0 0.3rem; }
h3 { font-size: 0.95rem; font-weight: 680; margin: 0; overflow-wrap: anywhere; }
dl { display: grid; gap: 0.75rem 1rem; grid-template-columns: repeat(3, minmax(0, 1fr)); margin: 1rem 0 0; }
dl > div { border-top: 1px solid var(--line); display: grid; gap: 0.34rem; padding-top: 0.65rem; }
dt { color: var(--text-tertiary); font-size: 0.68rem; font-weight: 700; }
dd { color: var(--text-secondary); font-size: 0.8rem; margin: 0; overflow-wrap: anywhere; }
.knowledge-document-detail__failure { color: var(--danger); }
.knowledge-document-detail__hash { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.7rem; }
.knowledge-document-detail__preview { border-top: 1px solid var(--line); color: var(--text-secondary); font-size: 0.78rem; margin-top: 1rem; padding-top: 1rem; }
.knowledge-document-detail__preview h4 { color: var(--text-primary); font-size: 0.86rem; font-weight: 680; margin: 0; }
.knowledge-document-detail__preview ol { display: grid; gap: 0.6rem; margin: 0.75rem 0 0; max-height: clamp(12rem, 34dvh, 24rem); overflow-y: auto; overscroll-behavior: contain; padding-left: 1.1rem; padding-right: 0.5rem; scrollbar-gutter: stable; }
.knowledge-document-detail__preview p { font-size: 0.75rem; line-height: 1.5; margin: 0.25rem 0 0; white-space: pre-wrap; }
@media (max-width: 760px) { .knowledge-document-detail, .knowledge-document-detail__preview ol { max-height: none; overflow: visible; overscroll-behavior: auto; scrollbar-gutter: auto; } dl { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
