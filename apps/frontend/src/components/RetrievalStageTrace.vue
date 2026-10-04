<script setup lang="ts">
import type { ReferenceSourceSseEvent } from "@agent-py/api-contracts";

import {
  formatPercentScore,
  formatRawScore,
  formatRetrievalStage
} from "../chat/retrievalPresentation";

type ChatReference = ReferenceSourceSseEvent["reference"];

const props = defineProps<{
  readonly compact?: boolean;
  readonly reference: ChatReference;
}>();

function vectorValue(): string {
  return formatRetrievalStage(
    props.reference.vectorRank,
    props.reference.vectorScore,
    formatPercentScore
  );
}

function bm25Value(): string {
  return formatRetrievalStage(
    props.reference.bm25Rank,
    props.reference.bm25Score,
    formatRawScore
  );
}

function rerankValue(): string {
  return formatRetrievalStage(
    props.reference.rerankRank,
    props.reference.rerankScore ?? props.reference.score,
    formatPercentScore
  );
}
</script>

<template>
  <dl
    class="retrieval-stage-trace"
    :class="{ 'retrieval-stage-trace--compact': compact }"
    :aria-label="`检索阶段：向量 ${vectorValue()}，BM25 ${bm25Value()}，精排 ${rerankValue()}`"
  >
    <div data-stage="vector"><dt>向量</dt><dd>{{ vectorValue() }}</dd></div>
    <div data-stage="bm25"><dt>BM25</dt><dd>{{ bm25Value() }}</dd></div>
    <div data-stage="rerank"><dt>精排</dt><dd>{{ rerankValue() }}</dd></div>
  </dl>
</template>

<style scoped>
.retrieval-stage-trace { display: flex; flex-wrap: wrap; gap: 0.45rem; margin: 0; }
.retrieval-stage-trace > div { align-items: baseline; background: var(--surface-hover); border-left: 2px solid var(--line-strong); border-radius: 0.25rem; display: inline-flex; gap: 0.35rem; min-width: 0; padding: 0.32rem 0.48rem; }
.retrieval-stage-trace > div[data-stage="vector"] { border-left-color: #4c7dba; }
.retrieval-stage-trace > div[data-stage="bm25"] { border-left-color: #a46b23; }
.retrieval-stage-trace > div[data-stage="rerank"] { border-left-color: var(--accent-strong); }
dt { color: var(--text-tertiary); font-size: 0.66rem; font-weight: 700; }
dd { color: var(--text-secondary); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.72rem; font-variant-numeric: tabular-nums; margin: 0; white-space: nowrap; }
.retrieval-stage-trace--compact { gap: 0.3rem; }
.retrieval-stage-trace--compact > div { background: transparent; border-radius: 0; padding: 0.12rem 0.4rem; }
@media (max-width: 640px) { .retrieval-stage-trace > div { flex: 1 1 8.5rem; } }
</style>
