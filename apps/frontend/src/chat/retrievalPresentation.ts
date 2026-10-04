export function formatPercentScore(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function formatRawScore(value: number): string {
  return value.toFixed(3);
}

export function formatRetrievalStage(
  rank: number | undefined,
  score: number | undefined,
  formatScore: (value: number) => string
): string {
  if (rank === undefined && score === undefined) return "未召回";
  const parts: string[] = [];
  if (rank !== undefined) parts.push(`#${rank}`);
  if (score !== undefined) parts.push(formatScore(score));
  return parts.join(" · ");
}
