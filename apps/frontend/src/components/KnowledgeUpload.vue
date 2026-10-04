<script setup lang="ts">
import { FileUp, LoaderCircle } from "lucide-vue-next";
import { computed, ref } from "vue";

import { DOCUMENT_UPLOAD_POLICY, type DocumentChunkingConfiguration } from "@agent-py/api-contracts";

import { supportedFormatsMessage, validateKnowledgeDocumentFile } from "../knowledge/documentPolicy";

const emit = defineEmits<{ upload: [file: File, chunking: DocumentChunkingConfiguration] }>();
const props = withDefaults(defineProps<{ readonly disabled: boolean; readonly isUploading?: boolean }>(), { isUploading: false });
const notice = ref<string | null>(null);
const strategy = ref<DocumentChunkingConfiguration["strategy"]>("fixed-character");
const maxCharacters = ref(1200);
const overlapCharacters = ref(200);
const usesFixedCharacter = computed(() => strategy.value === "fixed-character");

function buildChunkingConfiguration(): DocumentChunkingConfiguration {
  if (strategy.value === "fixed-character") {
    return {
      strategy: "fixed-character",
      maxCharacters: maxCharacters.value,
      overlapCharacters: overlapCharacters.value
    };
  }
  if (strategy.value === "markdown-heading") {
    return { strategy: "markdown-heading" };
  }
  return { strategy: "paragraph" };
}

function selectFile(file: File | null | undefined): void {
  if (file === null || file === undefined || props.disabled) return;
  const validationMessage = validateKnowledgeDocumentFile(file);
  if (validationMessage !== null) {
    notice.value = validationMessage;
    return;
  }
  notice.value = null;
  emit("upload", file, buildChunkingConfiguration());
}

function onChange(event: Event): void {
  const input = event.target as HTMLInputElement;
  selectFile(input.files?.[0]);
  input.value = "";
}

function onDrop(event: DragEvent): void {
  event.preventDefault();
  selectFile(event.dataTransfer?.files[0]);
}
</script>

<template>
  <section class="knowledge-upload" :class="{ 'knowledge-upload--disabled': disabled }" @dragover.prevent @drop="onDrop">
    <div class="knowledge-upload__icon"><LoaderCircle v-if="isUploading" class="knowledge-upload__spin" :size="20" aria-hidden="true" /><FileUp v-else :size="20" aria-hidden="true" /></div>
    <div>
      <h3>{{ isUploading ? "正在上传文档" : "上传知识文档" }}</h3>
      <p>{{ isUploading ? "文件已提交，正在创建索引任务。" : supportedFormatsMessage() }}</p>
      <p v-if="notice" class="knowledge-upload__notice" role="alert">{{ notice }}</p>
    </div>
    <label class="knowledge-upload__field">分片策略<select v-model="strategy" :disabled="disabled || isUploading"><option value="fixed-character">固定字符 + overlap</option><option value="markdown-heading">Markdown 标题/章节</option><option value="paragraph">段落边界</option></select></label>
    <template v-if="usesFixedCharacter">
      <label class="knowledge-upload__field">最大字符<input v-model.number="maxCharacters" :disabled="disabled || isUploading" min="100" max="5000" type="number"></label>
      <label class="knowledge-upload__field">overlap<input v-model.number="overlapCharacters" :disabled="disabled || isUploading" min="0" :max="maxCharacters - 1" type="number"></label>
    </template>
    <p v-else class="knowledge-upload__strategy-note">
      {{ strategy === "markdown-heading" ? "按 Markdown 标题组织分片，无需设置字符数和重叠参数。" : "按段落边界组织分片，无需设置字符数和重叠参数。" }}
    </p>
    <label class="knowledge-upload__select">
      <input :accept="DOCUMENT_UPLOAD_POLICY.allowedExtensions.join(',')" :disabled="disabled" type="file" @change="onChange">
      <span>{{ isUploading ? "上传中" : "选择文档" }}</span>
    </label>
  </section>
</template>

<style scoped>
.knowledge-upload { align-items: center; background: var(--surface-raised); border: 1px dashed var(--line-strong); border-radius: 0.5rem; display: grid; gap: 0.9rem; grid-template-columns: auto minmax(0, 1fr) auto auto auto auto; padding: 1rem; transition: border-color var(--transition-fast), background var(--transition-fast); }
.knowledge-upload:hover { border-color: var(--accent-border); }
.knowledge-upload--disabled { opacity: 0.72; }
.knowledge-upload__icon { align-items: center; background: var(--accent-soft); border-radius: 0.65rem; color: var(--accent-strong); display: inline-flex; height: 2.65rem; justify-content: center; width: 2.65rem; }
h3 { font-size: 0.9rem; font-weight: 680; margin: 0; }
p { color: var(--text-secondary); font-size: 0.78rem; line-height: 1.55; margin: 0.25rem 0 0; }
.knowledge-upload__notice { color: var(--danger); }
.knowledge-upload__select { align-items: center; background: var(--surface-raised); border: 1px solid var(--line-strong); border-radius: 0.45rem; color: var(--text-primary); cursor: pointer; display: inline-flex; font-size: 0.8rem; font-weight: 650; min-height: 2.4rem; padding: 0 0.75rem; white-space: nowrap; }
.knowledge-upload__select:hover { background: var(--surface-hover); }
.knowledge-upload__select input { height: 1px; opacity: 0; overflow: hidden; position: absolute; width: 1px; }
.knowledge-upload__field { color: var(--text-tertiary); display: grid; font-size: 0.68rem; font-weight: 700; gap: 0.2rem; }
.knowledge-upload__field select, .knowledge-upload__field input { background: var(--surface-raised); border: 1px solid var(--line-strong); border-radius: 0.35rem; color: var(--text-primary); font-size: 0.74rem; min-height: 2.25rem; padding: 0 0.35rem; }
.knowledge-upload__strategy-note { background: var(--surface); border: 1px solid var(--line); border-radius: 0.45rem; color: var(--text-tertiary); font-size: 0.72rem; line-height: 1.45; margin: 0; max-width: 15rem; padding: 0.48rem 0.58rem; }
.knowledge-upload__spin { animation: knowledge-upload-spin 0.9s linear infinite; }
@keyframes knowledge-upload-spin { to { transform: rotate(360deg); } }
@media (max-width: 860px) { .knowledge-upload { align-items: start; grid-template-columns: auto minmax(0, 1fr); } .knowledge-upload__field, .knowledge-upload__strategy-note, .knowledge-upload__select { grid-column: 2; justify-self: start; } }
</style>
