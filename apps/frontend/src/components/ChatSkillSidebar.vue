<script setup lang="ts">
import { Check, FileText, Trash2, Upload } from "lucide-vue-next";
import { computed, ref, watch } from "vue";

import type { ChatAssemblyConfigurationResponse } from "@agent-py/api-contracts";

const emit = defineEmits<{
  save: [systemPromptId: string, skillIds: readonly string[]];
  uploadSkill: [file: File];
  deleteSkill: [skillId: string];
}>();
const props = defineProps<{
  readonly configuration: ChatAssemblyConfigurationResponse | null;
  readonly isSaving: boolean;
}>();

const skillIds = ref<string[]>([]);
const notice = ref<string | null>(null);
const selectedPromptId = computed(() => props.configuration?.selection.systemPromptId ?? "");

watch(
  () => props.configuration,
  (value) => {
    if (value === null) return;
    skillIds.value = [...value.selection.skillIds];
  },
  { immediate: true }
);

function toggleSkill(skillId: string): void {
  skillIds.value = skillIds.value.includes(skillId)
    ? skillIds.value.filter((item) => item !== skillId)
    : [...skillIds.value, skillId];
}

function uploadSkill(event: Event): void {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (file === undefined) return;
  if (file.name !== "SKILL.md") {
    notice.value = "Skill 文件名必须严格为 SKILL.md。";
    return;
  }
  if (file.size === 0) {
    notice.value = "Skill 文件不能为空，请上传 UTF-8 Markdown 文本。";
    return;
  }
  if (file.size > 64 * 1024) {
    notice.value = "Skill 文件不能超过 64 KB。";
    return;
  }
  notice.value = null;
  emit("uploadSkill", file);
}

function saveSelection(): void {
  if (selectedPromptId.value.length === 0) {
    notice.value = "请先选择一个系统提示词。";
    return;
  }
  notice.value = null;
  emit("save", selectedPromptId.value, skillIds.value);
}
</script>

<template>
  <aside class="chat-skill-sidebar" aria-label="Skill 设置">
    <header class="chat-skill-sidebar__header">
      <div>
        <p>Skill 设置</p>
        <h3>模型按需加载所选 Skill</h3>
      </div>
      <label class="chat-skill-sidebar__upload" title="上传 Skill">
        <Upload :size="16" aria-hidden="true" />
        <input :disabled="isSaving" type="file" accept=".md" @change="uploadSkill">
      </label>
    </header>

    <section class="chat-skill-sidebar__rules" aria-label="Skill 上传规范">
      <strong>Skill 上传规范</strong>
      <ul>
        <li>文件名必须严格为 <code>SKILL.md</code>。</li>
        <li>YAML frontmatter 必须包含合法的 <code>name</code> 和 <code>description</code>。</li>
        <li>内容必须是 UTF-8 Markdown，不能为空。</li>
        <li>单个文件不能超过 64 KB。</li>
      </ul>
    </section>

    <p v-if="notice" class="chat-skill-sidebar__notice" role="alert">{{ notice }}</p>
    <p v-if="configuration === null" class="chat-skill-sidebar__empty">正在加载 Skill。</p>
    <p v-else-if="configuration.skills.length === 0" class="chat-skill-sidebar__empty">还没有上传 Skill。</p>

    <div v-else class="chat-skill-sidebar__list" role="list">
      <label v-for="skill in configuration.skills" :key="skill.id" class="chat-skill-sidebar__item" role="listitem">
        <input type="checkbox" :checked="skillIds.includes(skill.id)" :disabled="isSaving" @change="toggleSkill(skill.id)">
        <FileText :size="16" aria-hidden="true" />
        <span><strong>{{ skill.name }}</strong><small>{{ skill.description }}</small></span>
        <button :disabled="isSaving" type="button" title="删除 Skill" @click.prevent="emit('deleteSkill', skill.id)">
          <Trash2 :size="15" aria-hidden="true" />
        </button>
      </label>
    </div>

    <button class="chat-skill-sidebar__save" type="button" :disabled="isSaving || configuration === null" @click="saveSelection">
      <Check :size="15" aria-hidden="true" />{{ isSaving ? "保存中" : "保存使用的 Skill" }}
    </button>
  </aside>
</template>

<style scoped>
.chat-skill-sidebar { background: var(--surface-raised); border-left: 1px solid var(--line); border-top: 1px solid var(--line); display: grid; gap: 0.8rem; grid-auto-rows: max-content; min-width: 0; overflow: auto; padding: 1rem; }
.chat-skill-sidebar__header { align-items: center; display: flex; gap: 0.8rem; justify-content: space-between; }
.chat-skill-sidebar__header p { color: var(--text-primary); font-size: 0.86rem; font-weight: 760; margin: 0; }
.chat-skill-sidebar__header h3 { color: var(--text-tertiary); font-size: 0.72rem; font-weight: 650; margin: 0.22rem 0 0; }
.chat-skill-sidebar__upload { align-items: center; border: 1px solid var(--line-strong); border-radius: 0.5rem; cursor: pointer; display: inline-flex; height: 2.3rem; justify-content: center; transition: background var(--transition-fast), border-color var(--transition-fast); width: 2.3rem; }
.chat-skill-sidebar__upload:hover { background: var(--surface-hover); border-color: var(--accent-border); }
.chat-skill-sidebar__upload input { display: none; }
.chat-skill-sidebar__rules { background: var(--surface); border: 1px solid var(--line); border-radius: 0.5rem; padding: 0.7rem; }
.chat-skill-sidebar__rules strong { color: var(--text-primary); font-size: 0.76rem; }
.chat-skill-sidebar__rules ul { color: var(--text-secondary); display: grid; font-size: 0.72rem; gap: 0.35rem; line-height: 1.5; margin: 0.45rem 0 0; padding-left: 1rem; }
.chat-skill-sidebar__rules code { background: var(--surface-inset); border-radius: 0.28rem; color: var(--accent-strong); padding: 0.08rem 0.22rem; }
.chat-skill-sidebar__notice { background: var(--danger-soft); border: 1px solid var(--status-danger-border); border-radius: 0.5rem; color: var(--status-danger-text); font-size: 0.76rem; line-height: 1.5; margin: 0; padding: 0.55rem 0.65rem; }
.chat-skill-sidebar__empty { color: var(--text-tertiary); font-size: 0.78rem; margin: 0; }
.chat-skill-sidebar__list { display: grid; gap: 0.5rem; }
.chat-skill-sidebar__item { align-items: start; border: 1px solid var(--line); border-radius: 0.5rem; display: grid; gap: 0.5rem; grid-template-columns: auto auto minmax(0, 1fr) auto; padding: 0.58rem; }
.chat-skill-sidebar__item:hover { background: var(--surface-hover); }
.chat-skill-sidebar__item input { margin-top: 0.15rem; }
.chat-skill-sidebar__item span { display: grid; gap: 0.18rem; min-width: 0; }
.chat-skill-sidebar__item strong { color: var(--text-primary); font-size: 0.76rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chat-skill-sidebar__item small { color: var(--text-tertiary); display: -webkit-box; font-size: 0.7rem; font-weight: 500; line-height: 1.45; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }
.chat-skill-sidebar__item button { align-items: center; border: 1px solid var(--line); border-radius: 0.42rem; color: var(--danger); display: inline-flex; height: 2rem; justify-content: center; width: 2rem; }
.chat-skill-sidebar__save { align-items: center; background: var(--accent); border-radius: 0.45rem; color: white; display: inline-flex; font-size: 0.76rem; font-weight: 760; gap: 0.35rem; min-height: 2.35rem; padding: 0 0.72rem; width: fit-content; }
button:disabled, input:disabled { cursor: not-allowed; opacity: 0.55; }
@media (max-width: 1120px) { .chat-skill-sidebar { border-left: 0; } }
</style>
