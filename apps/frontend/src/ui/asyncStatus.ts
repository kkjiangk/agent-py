export type AsyncStatusTone = "neutral" | "waiting" | "running" | "success" | "danger";

export interface AsyncStatusDescription {
  readonly label: string;
  readonly tone: AsyncStatusTone;
  readonly active: boolean;
}

const STATUS_DESCRIPTIONS: Readonly<Record<string, AsyncStatusDescription>> = {
  pending: { label: "等待中", tone: "waiting", active: true },
  accepted: { label: "准备中", tone: "waiting", active: true },
  queued: { label: "排队中", tone: "waiting", active: true },
  started: { label: "正在调用", tone: "running", active: true },
  delta: { label: "正在返回结果", tone: "running", active: true },
  running: { label: "执行中", tone: "running", active: true },
  streaming: { label: "正在生成", tone: "running", active: true },
  indexing: { label: "正在索引", tone: "running", active: true },
  indexed: { label: "已索引", tone: "success", active: false },
  active: { label: "告警中", tone: "danger", active: true },
  succeeded: { label: "已完成", tone: "success", active: false },
  completed: { label: "已完成", tone: "success", active: false },
  cancelled: { label: "已取消", tone: "neutral", active: false },
  ready: { label: "已就绪", tone: "success", active: false },
  degraded: { label: "服务异常", tone: "danger", active: false },
  failed: { label: "执行失败", tone: "danger", active: false },
  error: { label: "执行失败", tone: "danger", active: false }
};

const UNKNOWN_STATUS: AsyncStatusDescription = {
  label: "状态未知",
  tone: "neutral",
  active: false
};

export function describeAsyncStatus(status: string | null | undefined): AsyncStatusDescription {
  if (status === null || status === undefined) {
    return UNKNOWN_STATUS;
  }
  return STATUS_DESCRIPTIONS[status.toLowerCase()] ?? UNKNOWN_STATUS;
}
