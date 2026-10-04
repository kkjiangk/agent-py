<script setup lang="ts">
import { ChevronRight, FileText, RotateCw, Trash2 } from "lucide-vue-next";

import type { DocumentChunkPreview, DocumentIndexTask, KnowledgeDocument } from "@agent-py/api-contracts";

import AsyncStatusBadge from "./AsyncStatusBadge.vue";
import KnowledgeDocumentDetail from "./KnowledgeDocumentDetail.vue";

const emit = defineEmits<{
  close: [];
  delete: [document: KnowledgeDocument];
  detail: [document: KnowledgeDocument];
  rebuild: [document: KnowledgeDocument];
  retry: [task: DocumentIndexTask];
}>();

const props = defineProps<{
  readonly documents: readonly KnowledgeDocument[];
  readonly indexTasks: readonly DocumentIndexTask[];
  readonly preview?: DocumentChunkPreview | null;
  readonly selectedDocument?: KnowledgeDocument | null;
}>();

function latestTask(document: KnowledgeDocument): DocumentIndexTask | undefined {
  return props.indexTasks.find((task) => task.documentId === document.id);
}

function indexLabel(document: KnowledgeDocument): string {
  return latestTask(document)?.status ?? document.indexStatus;
}

function isSelected(document: KnowledgeDocument): boolean {
  return props.selectedDocument?.id === document.id;
}

function toggleDetail(event: Event, document: KnowledgeDocument): void {
  const disclosure = event.currentTarget as HTMLDetailsElement;
  if (disclosure.open) {
    emit("detail", document);
    return;
  }
  if (isSelected(document)) emit("close");
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}
</script>

<template>
  <div class="knowledge-document-list">
    <table>
      <thead><tr><th>文档</th><th>上传时间</th><th>索引状态</th><th><span class="sr-only">操作</span></th></tr></thead>
      <tbody>
        <template v-for="document in documents" :key="document.id">
        <tr>
          <td data-label="文档">
            <div class="knowledge-document-list__document">
              <FileText :size="17" aria-hidden="true" /><span><strong>{{ document.filename }}</strong><small>{{ formatSize(document.sizeBytes) }} · {{ document.mimeType }}</small></span>
            </div>
          </td>
          <td data-label="上传时间"><time :datetime="document.uploadedAt">{{ formatDate(document.uploadedAt) }}</time></td>
          <td data-label="索引状态">
            <AsyncStatusBadge :status="indexLabel(document)" compact />
            <small v-if="latestTask(document)?.failureReason" class="knowledge-document-list__failure">{{ latestTask(document)?.failureReason }}</small>
          </td>
          <td class="knowledge-document-list__actions" data-label="操作">
            <button v-if="latestTask(document)?.status === 'failed'" type="button" title="重试索引" aria-label="重试索引" @click="emit('retry', latestTask(document)!)"><RotateCw :size="16" aria-hidden="true" /></button>
            <button v-else type="button" title="重建索引" aria-label="重建索引" @click="emit('rebuild', document)"><RotateCw :size="16" aria-hidden="true" /></button>
            <button type="button" title="删除文档" aria-label="删除文档" class="knowledge-document-list__delete" @click="emit('delete', document)"><Trash2 :size="16" aria-hidden="true" /></button>
          </td>
        </tr>
        <tr class="knowledge-document-list__detail-row">
          <td colspan="4">
            <details class="knowledge-document-list__detail" @toggle="toggleDetail($event, document)">
              <summary><ChevronRight :size="15" aria-hidden="true" />展开文档详情与分片预览</summary>
              <KnowledgeDocumentDetail v-if="isSelected(document)" :document="selectedDocument!" :preview="preview ?? null" :task="latestTask(document)" />
              <p v-else class="knowledge-document-list__loading">正在加载文档详情与分片预览...</p>
            </details>
          </td>
        </tr>
        </template>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.knowledge-document-list { min-height: 0; overflow: auto; overscroll-behavior: contain; scrollbar-gutter: stable; }
table { border-collapse: collapse; min-width: 38rem; width: 100%; }
th { color: var(--text-tertiary); font-size: 0.72rem; font-weight: 700; padding: 0.72rem 0.85rem; text-align: left; }
td { border-top: 1px solid var(--line); color: var(--text-secondary); font-size: 0.82rem; padding: 0.8rem 0.85rem; vertical-align: middle; }
.knowledge-document-list__document { align-items: center; display: flex; gap: 0.6rem; min-width: 0; text-align: left; }
.knowledge-document-list__document span { display: grid; min-width: 0; }
strong { color: var(--text-primary); font-size: 0.84rem; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
small { color: var(--text-tertiary); font-size: 0.72rem; margin-top: 0.2rem; }
.knowledge-document-list__failure { color: var(--danger); display: block; max-width: 14rem; overflow-wrap: anywhere; }
.knowledge-document-list__actions { display: flex; gap: 0.2rem; justify-content: end; white-space: nowrap; }
.knowledge-document-list__actions button { align-items: center; border-radius: 0.42rem; color: var(--text-secondary); display: inline-flex; height: 2rem; justify-content: center; width: 2rem; }
.knowledge-document-list__actions button:hover { background: var(--surface-hover); color: var(--accent-strong); }
.knowledge-document-list__actions .knowledge-document-list__delete:hover { color: var(--danger); }
.knowledge-document-list__detail-row td { background: #fbfbfc; padding: 0; }
.knowledge-document-list__detail { min-width: 0; }
.knowledge-document-list__detail summary { align-items: center; color: var(--text-secondary); cursor: pointer; display: flex; font-size: 0.78rem; font-weight: 680; gap: 0.35rem; padding: 0.72rem 0.9rem; }
.knowledge-document-list__detail summary:hover { background: var(--surface-hover); color: var(--accent-strong); }
.knowledge-document-list__detail[open] summary { border-bottom: 1px solid var(--line); color: var(--text-primary); }
.knowledge-document-list__detail summary svg { transition: transform var(--transition-fast); }
.knowledge-document-list__detail[open] summary svg { transform: rotate(90deg); }
.knowledge-document-list__loading { color: var(--text-tertiary); font-size: 0.78rem; margin: 0; padding: 1rem 1.15rem; }
.sr-only { clip: rect(0, 0, 0, 0); clip-path: inset(50%); height: 1px; overflow: hidden; position: absolute; white-space: nowrap; width: 1px; }
@media (max-width: 620px) { .knowledge-document-list { overflow: visible; overscroll-behavior: auto; scrollbar-gutter: auto; } table, tbody, tr, td { display: block; min-width: 0; width: 100%; } thead { display: none; } tr { border-top: 1px solid var(--line); padding: 0.45rem 0; } td { align-items: center; border: 0; display: flex; justify-content: space-between; padding: 0.45rem 0.25rem; } td::before { color: var(--text-tertiary); content: attr(data-label); font-size: 0.7rem; font-weight: 700; margin-right: 1rem; } td:first-child::before { display: none; } .knowledge-document-list__document { width: 100%; } .knowledge-document-list__actions { justify-content: start; } }
</style>
