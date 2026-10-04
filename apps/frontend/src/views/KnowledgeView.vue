<script setup lang="ts">
import { AlertTriangle, Database, FileWarning } from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import type { DocumentIndexTask, KnowledgeDocument } from "@agent-py/api-contracts";

import AppEmptyState from "../components/AppEmptyState.vue";
import AppErrorState from "../components/AppErrorState.vue";
import AppLoadingState from "../components/AppLoadingState.vue";
import KnowledgeDocumentList from "../components/KnowledgeDocumentList.vue";
import KnowledgeUpload from "../components/KnowledgeUpload.vue";
import { useKnowledgeStore } from "../stores/knowledge";

const knowledge = useKnowledgeStore();
const route = useRoute();
const pendingDeletion = ref<KnowledgeDocument | null>(null);

onMounted(() => { void initializeFromCitation().catch(() => undefined); });
onBeforeUnmount(() => { knowledge.stopPolling(); });

function run(operation: () => Promise<unknown>): void { void operation().catch(() => undefined); }
function openDocument(document: KnowledgeDocument): void { run(() => knowledge.openDocument(document)); }

async function initializeFromCitation(): Promise<void> {
  await knowledge.initialize();
  const knowledgeBaseId = route.query.knowledgeBaseId;
  if (typeof knowledgeBaseId === "string" && knowledgeBaseId !== knowledge.selectedKnowledgeBaseId) {
    await knowledge.selectKnowledgeBase(knowledgeBaseId);
  }
  const documentId = route.query.documentId;
  if (typeof documentId !== "string") return;
  const document = knowledge.documents.find((item) => item.id === documentId);
  if (document !== undefined) await knowledge.openDocument(document);
}

function confirmDelete(): void {
  const document = pendingDeletion.value;
  if (document === null) return;
  run(async () => {
    await knowledge.deleteDocument(document);
    pendingDeletion.value = null;
  });
}

function uploadDocument(file: File, chunking: import("@agent-py/api-contracts").DocumentChunkingConfiguration): void {
  run(() => knowledge.upload(file, chunking));
}
</script>

<template>
  <section class="knowledge-view" aria-label="知识库工作区">
    <header class="knowledge-view__header">
      <div><p>你的知识库</p><h2>文档与索引</h2><span>上传 SOP、复盘和运行手册，让模型在需要时检索可靠来源。</span></div>
      <label v-if="knowledge.knowledgeBases.length > 1" class="knowledge-view__base"><span>当前知识库</span><select :value="knowledge.selectedKnowledgeBaseId ?? ''" :disabled="knowledge.isLoading" aria-label="当前知识库" @change="run(() => knowledge.selectKnowledgeBase(($event.target as HTMLSelectElement).value))"><option v-for="base in knowledge.knowledgeBases" :key="base.id" :value="base.id">{{ base.name }}</option></select></label>
    </header>

    <AppLoadingState v-if="knowledge.isLoading && knowledge.documents.length === 0" label="正在加载知识库" />
    <AppErrorState v-else-if="knowledge.errorMessage && knowledge.documents.length === 0" :can-retry="true" :message="knowledge.errorMessage" @retry="run(knowledge.initialize)" />
    <template v-else>
      <KnowledgeUpload :disabled="knowledge.isUploading || knowledge.selectedKnowledgeBaseId === null" :is-uploading="knowledge.isUploading" @upload="uploadDocument" />
      <section v-if="knowledge.pendingOverwriteFile" class="knowledge-view__confirmation" role="alert"><FileWarning :size="18" aria-hidden="true" /><div><strong>发现同名文档</strong><p>{{ knowledge.pendingOverwriteFile.name }} 会替换现有文档及其向量数据。</p></div><div><button type="button" @click="knowledge.clearPendingOverwrite">取消</button><button type="button" class="knowledge-view__danger-command" @click="run(knowledge.overwritePendingUpload)">确认替换</button></div></section>
      <div class="knowledge-view__body">
        <section class="knowledge-view__documents" aria-labelledby="knowledge-documents-heading">
          <header><div><p>已上传文档</p><h3 id="knowledge-documents-heading">{{ knowledge.documents.length }} 份资料</h3></div><Database :size="19" aria-hidden="true" /></header>
          <AppEmptyState v-if="knowledge.documents.length === 0" title="还没有文档" detail="上传一份 SOP、故障复盘或运行手册，让它在对话和诊断中成为可信来源。" />
          <KnowledgeDocumentList v-else :documents="knowledge.documents" :index-tasks="knowledge.indexTasks" :preview="knowledge.chunkPreview" :selected-document="knowledge.selectedDocument" @close="knowledge.closeDocument" @delete="pendingDeletion = $event" @detail="openDocument" @rebuild="run(() => knowledge.rebuildDocumentIndex($event))" @retry="run(() => knowledge.retryIndexTask($event))" />
        </section>
      </div>
    </template>

    <section v-if="pendingDeletion" class="knowledge-view__confirmation knowledge-view__confirmation--delete" role="alertdialog" aria-label="确认删除文档"><AlertTriangle :size="18" aria-hidden="true" /><div><strong>删除 {{ pendingDeletion.filename }}？</strong><p>此操作会删除文档记录和已建立的向量索引。</p></div><div><button type="button" @click="pendingDeletion = null">取消</button><button type="button" class="knowledge-view__danger-command" @click="confirmDelete">确认删除</button></div></section>
  </section>
</template>

<style scoped>
.knowledge-view { background: var(--surface); box-sizing: border-box; display: flex; flex-direction: column; gap: 1rem; height: 100%; min-height: 0; overflow: hidden; padding: clamp(1rem, 2.2vw, 2rem); }
.knowledge-view__header { align-items: end; display: flex; gap: 1.5rem; justify-content: space-between; }
.knowledge-view__header p, .knowledge-view__documents > header p { color: var(--text-tertiary); font-size: 0.72rem; font-weight: 700; margin: 0 0 0.35rem; }
h2 { font-size: 1.45rem; font-weight: 710; margin: 0; }
.knowledge-view__header > div > span { color: var(--text-secondary); display: block; font-size: 0.88rem; line-height: 1.6; margin-top: 0.45rem; max-width: 42rem; }
.knowledge-view__base { display: grid; gap: 0.35rem; min-width: min(16rem, 100%); }
.knowledge-view__base > span { color: var(--text-tertiary); font-size: 0.7rem; font-weight: 700; }
select { background: var(--surface-raised); border: 1px solid var(--line-strong); border-radius: 0.45rem; color: var(--text-primary); min-height: 2.55rem; padding: 0 0.65rem; }
.knowledge-view__body { background: var(--surface-raised); border: 1px solid var(--line); border-radius: var(--radius-lg); display: grid; flex: 1 1 auto; min-height: 0; min-width: 0; overflow: hidden; }
.knowledge-view__documents { display: grid; grid-template-rows: auto minmax(0, 1fr); min-height: 0; min-width: 0; overflow: hidden; }
.knowledge-view__documents > header { align-items: center; border-bottom: 1px solid var(--line); display: flex; justify-content: space-between; min-height: 4.25rem; padding: 0.8rem 1rem; }
.knowledge-view__documents > header h3 { font-size: 0.98rem; font-weight: 680; margin: 0; }
.knowledge-view__documents > .empty-state { margin: 0 1rem; }
.knowledge-view__confirmation { align-items: center; background: var(--status-waiting-bg); border: 1px solid var(--status-waiting-border); border-radius: var(--radius-md); display: grid; gap: 0.8rem; grid-template-columns: auto minmax(0, 1fr) auto; padding: 0.75rem 1rem; }
.knowledge-view__confirmation > svg { color: var(--status-waiting-text); }
.knowledge-view__confirmation strong { font-size: 0.84rem; }
.knowledge-view__confirmation p { color: var(--text-secondary); font-size: 0.78rem; margin: 0.25rem 0 0; }
.knowledge-view__confirmation > div:last-child { display: flex; gap: 0.45rem; }
.knowledge-view__confirmation button { border: 1px solid var(--line-strong); border-radius: 0.4rem; font-size: 0.78rem; min-height: 2rem; padding: 0 0.55rem; white-space: nowrap; }
.knowledge-view__confirmation button:hover { background: rgb(255 255 255 / 65%); }
.knowledge-view__confirmation .knowledge-view__danger-command { border-color: var(--danger); color: var(--danger); }
.knowledge-view__confirmation--delete { background: var(--danger-soft); border-color: var(--status-danger-border); }
@media (max-width: 680px) { .knowledge-view { height: auto; min-height: 100%; overflow-y: auto; } .knowledge-view__body { flex: 0 0 auto; overflow: visible; } .knowledge-view__documents { display: block; overflow: visible; } .knowledge-view__header { align-items: stretch; flex-direction: column; gap: 1rem; } .knowledge-view__base { min-width: 0; } .knowledge-view__confirmation { align-items: start; grid-template-columns: auto minmax(0, 1fr); } .knowledge-view__confirmation > div:last-child { flex-wrap: wrap; grid-column: 2; } }
</style>
