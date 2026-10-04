import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it } from "vitest";

import type {
  AiopsDiagnosticEvidenceChain,
  AiopsDiagnosticSummary,
  SseEvent
} from "@agent-py/api-contracts";

import type { AiopsClient } from "../src/aiops/aiopsClient";
import { setAiopsClientFactoryForTests, useAiopsStore } from "../src/stores/aiops";

const task = (overrides: Partial<AiopsDiagnosticSummary> = {}): AiopsDiagnosticSummary => ({
  id: "diagnostic_1",
  ownerUserId: "user_1",
  status: "accepted",
  query: "Investigate elevated API latency",
  inputPayload: { query: "Investigate elevated API latency", alert: {} },
  resultPayload: {},
  createdAt: "2026-07-10T00:00:00.000Z",
  updatedAt: "2026-07-10T00:00:00.000Z",
  completedAt: null,
  reports: [],
  ...overrides
});

const chain = (): AiopsDiagnosticEvidenceChain => ({
  task: task({
    completedAt: "2026-07-10T00:00:04.000Z",
    reports: [{
      id: "report_1",
      title: "AIOps evidence-based diagnostic report",
      content: "## Finding\n\nThe API was slow.",
      payload: {},
      evidenceIds: ["evidence_1"],
      createdAt: "2026-07-10T00:00:04.000Z"
    }],
    status: "succeeded"
  }),
  steps: [{
    id: "step_1",
    taskId: "diagnostic_1",
    sequence: 1,
    phase: "planner",
    status: "completed",
    payload: {},
    createdAt: "2026-07-10T00:00:01.000Z"
  }],
  toolCalls: [{
    id: "tool_1",
    ownerUserId: "user_1",
    sessionId: null,
    diagnosticTaskId: "diagnostic_1",
    toolName: "SearchLog",
    status: "completed",
    arguments: { query: "latency" },
    resultSummary: "Found latency spike.",
    errorMessage: null,
    startedAt: "2026-07-10T00:00:01.000Z",
    completedAt: "2026-07-10T00:00:02.000Z",
    durationMs: 50,
    createdAt: "2026-07-10T00:00:01.000Z"
  }],
  evidence: [{
    id: "evidence_1",
    taskId: "diagnostic_1",
    stepId: "step_1",
    toolCallId: "tool_1",
    kind: "log",
    source: "SearchLog",
    summary: "Latency spike at 10:00.",
    payload: { matched: 1 },
    createdAt: "2026-07-10T00:00:02.000Z"
  }],
  reports: [{
    id: "report_1",
    title: "AIOps evidence-based diagnostic report",
    content: "## Finding\n\nThe API was slow.",
    payload: {},
    evidenceIds: ["evidence_1"],
    createdAt: "2026-07-10T00:00:04.000Z"
  }],
  reportEvidenceLinks: [{
    id: "link_1",
    taskId: "diagnostic_1",
    reportId: "report_1",
    evidenceId: "evidence_1",
    createdAt: "2026-07-10T00:00:04.000Z"
  }],
  checkpoints: []
});

const events: readonly SseEvent[] = [
  {
    id: "event_1",
    type: "task.status",
    channel: "aiops",
    timestamp: "2026-07-10T00:00:01.000Z",
    task: { id: "diagnostic_1", status: "running", progress: 15, message: "Planner: retrieving SOP evidence." }
  },
  {
    id: "event_2",
    type: "tool.call",
    channel: "aiops",
    timestamp: "2026-07-10T00:00:02.000Z",
    toolCall: { id: "tool_1", name: "SearchLog", status: "completed", output: { matches: 1 } }
  },
  {
    id: "event_3",
    type: "reference.source",
    channel: "aiops",
    timestamp: "2026-07-10T00:00:02.000Z",
    reference: { id: "reference_1", title: "Latency runbook", sourceType: "knowledge-base", score: 0.92 }
  },
  {
    id: "event_4",
    type: "report",
    channel: "aiops",
    timestamp: "2026-07-10T00:00:04.000Z",
    report: { id: "report_1", title: "AIOps evidence-based diagnostic report", content: "## Finding\n\nThe API was slow.", format: "markdown" }
  },
  { id: "event_5", type: "complete", channel: "aiops", timestamp: "2026-07-10T00:00:04.000Z" }
];

afterEach(() => setAiopsClientFactoryForTests(null));

describe("AIOps store", () => {
  it("creates a diagnostic, projects shared SSE events, and reconciles its persisted evidence chain", async () => {
    setAiopsClientFactoryForTests(() => fakeClient());
    setActivePinia(createPinia());
    const store = useAiopsStore();

    await store.initialize();
    await store.runDiagnostic("Investigate elevated API latency", { severity: "high" });

    expect(store.activeDiagnosticId).toBe("diagnostic_1");
    expect(store.liveEvents.map((event) => event.type)).toEqual(events.map((event) => event.type));
    expect(store.evidenceChain?.reports[0]?.evidenceIds).toEqual(["evidence_1"]);
    expect(store.isRunning).toBe(false);
  });

  it("loads the selected persisted evidence chain from the server-backed history", async () => {
    setAiopsClientFactoryForTests(() => fakeClient());
    setActivePinia(createPinia());
    const store = useAiopsStore();

    await store.initialize();
    await store.selectDiagnostic("diagnostic_1");

    expect(store.history[0]).toMatchObject({ id: "diagnostic_1", status: "succeeded" });
    expect(store.evidenceChain?.evidence[0]?.summary).toContain("Latency spike");
  });

  it("surfaces a streamed diagnostic error without inventing a completed report", async () => {
    const failed: SseEvent = {
      id: "event_error",
      type: "error",
      channel: "aiops",
      timestamp: "2026-07-10T00:00:02.000Z",
      error: { code: "SYSTEM_UNAVAILABLE", category: "system", httpStatus: 503, message: "CLS unavailable." }
    };
    setAiopsClientFactoryForTests(() => fakeClient({ streamed: [failed] }));
    setActivePinia(createPinia());
    const store = useAiopsStore();

    await store.runDiagnostic("Inspect logs");

    expect(store.errorMessage).toBe("服务暂时不可用，请稍后重试。");
    expect(store.liveEvents).toEqual([failed]);
  });
});

function fakeClient(options: { readonly streamed?: readonly SseEvent[] } = {}): AiopsClient {
  return {
    createDiagnostic: async () => task(),
    getEvidenceChain: async () => chain(),
    listActiveAlerts: async () => ({ items: [] }),
    listDiagnosticCases: async () => ({ items: [] }),
    listDiagnostics: async () => ({ items: [task()] }),
    saveDiagnosticCase: async () => ({
      document: {
        id: "doc_case_1", knowledgeBaseId: "kb_1", ownerUserId: "user_1", filename: "case.md", sizeBytes: 1, mimeType: "text/markdown", contentHash: "sha256:case", status: "ready", indexStatus: "pending", uploadedAt: "2026-07-10T00:00:00Z", updatedAt: "2026-07-10T00:00:00Z"
      },
      task: { id: "index_case_1", ownerUserId: "user_1", knowledgeBaseId: "kb_1", documentId: "doc_case_1", status: "pending", failureReason: null, retryOfTaskId: null, createdAt: "2026-07-10T00:00:00Z", updatedAt: "2026-07-10T00:00:00Z", startedAt: null, completedAt: null },
      scheduled: true as const
    }),
    streamDiagnostic: async function* (): AsyncIterable<SseEvent> {
      for (const event of options.streamed ?? events) yield event;
    }
  };
}
