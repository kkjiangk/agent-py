<script setup lang="ts">
import DOMPurify from "dompurify";
import { Marked } from "marked";
import { computed } from "vue";

const props = withDefaults(defineProps<{
  readonly content: string;
  readonly mode?: "compact" | "report";
}>(), { mode: "compact" });
const parser = new Marked({ breaks: true, gfm: true });
parser.use({ renderer: { html: () => "" } });

const renderedContent = computed(() =>
  DOMPurify.sanitize(parser.parse(props.content) as string, { USE_PROFILES: { html: true } })
);
</script>

<template>
  <div :class="['markdown-content', `markdown-content--${props.mode}`]" v-html="renderedContent" />
</template>

<style scoped>
.markdown-content :deep(*:first-child) { margin-top: 0; }
.markdown-content :deep(*:last-child) { margin-bottom: 0; }
.markdown-content :deep(p), .markdown-content :deep(ul), .markdown-content :deep(ol), .markdown-content :deep(pre) { margin: 0.7rem 0; }
.markdown-content :deep(h1), .markdown-content :deep(h2), .markdown-content :deep(h3) { font-size: 1rem; margin: 1rem 0 0.55rem; }
.markdown-content :deep(ul), .markdown-content :deep(ol) { padding-left: 1.3rem; }
.markdown-content :deep(code) { background: #edf3f2; color: #17534e; font-size: 0.88em; padding: 0.1rem 0.25rem; }
.markdown-content :deep(pre) { background: #172831; color: #e5f5f1; overflow-x: auto; padding: 0.9rem; }
.markdown-content :deep(pre code) { background: transparent; color: inherit; padding: 0; }
.markdown-content :deep(a) { color: var(--accent-strong); }
.markdown-content--report { color: var(--text-primary); font-size: 0.94rem; line-height: 1.75; min-width: 0; overflow-wrap: anywhere; word-break: break-word; }
.markdown-content--report :deep(h1) { border-bottom: 1px solid var(--line-strong); font-size: 1.5rem; line-height: 1.35; margin: 0 0 1.5rem; padding-bottom: 0.8rem; }
.markdown-content--report :deep(h2) { color: var(--text-primary); font-size: 1.12rem; line-height: 1.45; margin: 2rem 0 0.85rem; }
.markdown-content--report :deep(h3) { color: var(--text-secondary); font-size: 0.96rem; line-height: 1.5; margin: 1.35rem 0 0.55rem; }
.markdown-content--report :deep(p), .markdown-content--report :deep(ul), .markdown-content--report :deep(ol) { margin: 0.65rem 0; }
.markdown-content--report :deep(hr) { border: 0; border-top: 1px solid var(--line); margin: 1.75rem 0; }
.markdown-content--report :deep(strong) { color: var(--text-primary); font-weight: 700; }
.markdown-content--report :deep(table) { border-collapse: collapse; display: block; font-size: 0.78rem; margin: 1rem 0 1.5rem; max-width: 100%; overflow-x: auto; width: 100%; }
.markdown-content--report :deep(th), .markdown-content--report :deep(td) { border: 1px solid var(--line); min-width: 7rem; padding: 0.6rem 0.7rem; text-align: left; vertical-align: top; }
.markdown-content--report :deep(th) { background: var(--surface-inset); color: var(--text-secondary); font-weight: 700; white-space: nowrap; }
.markdown-content--report :deep(tr:nth-child(even) td) { background: #fafafa; }
.markdown-content--report :deep(blockquote) { border-left: 3px solid var(--accent-border); color: var(--text-secondary); margin: 1rem 0; padding: 0.2rem 0 0.2rem 0.9rem; }
@media (max-width: 560px) { .markdown-content--report { font-size: 0.9rem; } .markdown-content--report :deep(h1) { font-size: 1.3rem; } .markdown-content--report :deep(h2) { font-size: 1.04rem; } }
</style>
