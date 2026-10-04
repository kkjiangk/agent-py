<script setup lang="ts">
import { FileCheck2, FileClock, FileWarning } from "lucide-vue-next";

import MarkdownContent from "./MarkdownContent.vue";
import UserFeedbackControl from "./UserFeedbackControl.vue";

export interface AiopsReportDisplay {
  readonly id: string;
  readonly title: string;
  readonly content: string;
  readonly createdAt: string | null;
}

defineProps<{
  readonly report: AiopsReportDisplay | null;
  readonly isRunning: boolean;
  readonly hasTask: boolean;
  readonly taskFailed: boolean;
}>();
</script>

<template>
  <section class="aiops-report" aria-label="最终诊断报告" aria-live="polite">
    <header class="aiops-report__header">
      <div>
        <p>诊断产物</p>
        <h3>最终诊断报告</h3>
      </div>
      <span v-if="report" class="aiops-report__state aiops-report__state--ready">
        <FileCheck2 :size="15" aria-hidden="true" />已沉淀
      </span>
      <span v-else-if="isRunning" class="aiops-report__state aiops-report__state--running">
        <FileClock :size="15" aria-hidden="true" />生成中
      </span>
    </header>

    <article v-if="report" class="aiops-report__document">
      <div class="aiops-report__meta">
        <strong>{{ report.title }}</strong>
        <time v-if="report.createdAt" :datetime="report.createdAt">
          {{ new Date(report.createdAt).toLocaleString("zh-CN") }}
        </time>
      </div>
      <MarkdownContent :content="report.content" mode="report" />
      <footer><UserFeedbackControl target-type="diagnostic_report" :target-id="report.id" /></footer>
    </article>

    <div v-else-if="isRunning" class="aiops-report__empty aiops-report__empty--running">
      <FileClock :size="22" aria-hidden="true" />
      <div>
        <strong>正在等待诊断证据汇总</strong>
        <p>完成规划、工具查询与重规划后，将自动生成并保存中文诊断报告。</p>
      </div>
    </div>

    <div v-else-if="taskFailed" class="aiops-report__empty aiops-report__empty--failed">
      <FileWarning :size="22" aria-hidden="true" />
      <div>
        <strong>本次诊断未沉淀报告</strong>
        <p>诊断在报告持久化前失败，请查看下方过程和右侧工具证据后重新执行。</p>
      </div>
    </div>

    <div v-else class="aiops-report__empty">
      <FileClock :size="22" aria-hidden="true" />
      <div>
        <strong>{{ hasTask ? "报告尚未生成" : "等待诊断任务" }}</strong>
        <p>{{ hasTask ? "任务完成后，最终报告会沉淀在这里。" : "选择历史诊断或发起新任务后，在这里阅读最终报告。" }}</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.aiops-report { border-bottom: 1px solid var(--line); display: grid; grid-template-rows: auto minmax(0, 1fr); min-height: 0; min-width: 0; overflow: hidden; padding: 1.25rem; }
.aiops-report__header { align-items: center; display: flex; justify-content: space-between; }
.aiops-report__header p { color: var(--text-tertiary); font-size: 0.7rem; font-weight: 700; margin: 0 0 0.3rem; }
.aiops-report__header h3 { font-size: 1rem; font-weight: 720; margin: 0; }
.aiops-report__state { align-items: center; border: 1px solid; display: inline-flex; font-size: 0.72rem; font-weight: 700; gap: 0.35rem; min-height: 2rem; padding: 0.25rem 0.55rem; }
.aiops-report__state--ready { background: var(--status-success-bg); border-color: var(--status-success-border); color: var(--status-success-text); }
.aiops-report__state--running { background: var(--status-running-bg); border-color: var(--status-running-border); color: var(--status-running-text); }
.aiops-report__document { background: var(--surface-raised); border: 1px solid var(--line); display: grid; grid-template-rows: auto minmax(0, 1fr) auto; margin-top: 1rem; min-height: 0; min-width: 0; overflow: hidden; }
.aiops-report__meta { align-items: baseline; border-bottom: 1px solid var(--line); display: flex; gap: 0.75rem; justify-content: space-between; padding: 0.8rem 1rem; }
.aiops-report__meta strong { font-size: 0.84rem; font-weight: 700; }
.aiops-report__meta time { color: var(--text-tertiary); font-size: 0.72rem; white-space: nowrap; }
.aiops-report__document > :deep(.markdown-content) { min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: clamp(1rem, 3vw, 2rem); }
.aiops-report__document footer { border-top: 1px solid var(--line); padding: 0.65rem 1rem; }
.aiops-report__empty { align-items: center; background: var(--surface); border: 1px dashed var(--line-strong); color: var(--text-tertiary); display: flex; gap: 0.85rem; margin-top: 1rem; min-height: 6.5rem; padding: 1rem; }
.aiops-report__empty svg { flex: 0 0 auto; }
.aiops-report__empty strong { color: var(--text-secondary); display: block; font-size: 0.84rem; }
.aiops-report__empty p { font-size: 0.78rem; line-height: 1.55; margin: 0.3rem 0 0; }
.aiops-report__empty--running { background: var(--status-running-bg); border-color: var(--status-running-border); color: var(--status-running-text); }
.aiops-report__empty--failed { background: var(--status-danger-bg); border-color: var(--status-danger-border); color: var(--status-danger-text); }
@media (max-width: 560px) { .aiops-report { padding: 1rem; } .aiops-report__meta { align-items: flex-start; flex-direction: column; } .aiops-report__meta time { white-space: normal; } }
</style>
