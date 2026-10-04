// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AiopsDiagnosticEvidenceChain, AiopsDiagnosticSummary, SseEvent } from "@agent-py/api-contracts";

import AiopsEvidenceChain from "../src/components/AiopsEvidenceChain.vue";
import AiopsCaseLibrary from "../src/components/AiopsCaseLibrary.vue";
import AiopsReportPanel from "../src/components/AiopsReportPanel.vue";
import AiopsRunForm from "../src/components/AiopsRunForm.vue";
import AiopsTimeline from "../src/components/AiopsTimeline.vue";

beforeEach(() => {
  setActivePinia(createPinia());
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: true, data: { items: [] } }), {
    headers: { "Content-Type": "application/json" },
    status: 200
  })));
});

describe("AIOps components", () => {
  it("validates optional alert context before creating a diagnosis", async () => {
    const wrapper = mount(AiopsRunForm, { props: { disabled: false, isRunning: false } });
    await wrapper.get('textarea[aria-label="诊断问题"]').setValue("Inspect latency");
    await wrapper.get('textarea[aria-label="告警上下文"]') .setValue("{not-json");
    await wrapper.get('button[type="submit"]').trigger("submit");

    expect(wrapper.text()).toContain("有效的 JSON 对象");
    expect(wrapper.emitted("run")).toBeUndefined();
  });

  it("renders a readable execution chain with collapsed tool summaries and no raw JSON", () => {
    const event: SseEvent = {
      id: "event_1",
      type: "tool.call",
      channel: "aiops",
      timestamp: "2026-07-10T00:00:01.000Z",
      toolCall: { id: "tool_1", name: "SearchLog", status: "completed", output: { raw: "x".repeat(400) } }
    };
    const chain: AiopsDiagnosticEvidenceChain = {
      task: diagnostic(),
      steps: [
        { id: "step_1", taskId: "diagnostic_1", sequence: 1, phase: "planner", status: "completed", payload: { noSopMatched: true, plan: [{ tool: "SearchLog", purpose: "查询告警窗口日志" }] }, createdAt: "2026-07-10T00:00:00.000Z" },
        { id: "step_2", taskId: "diagnostic_1", sequence: 2, phase: "executor", status: "completed", payload: { tool: "SearchLog", planStep: { purpose: "查询告警窗口日志" } }, createdAt: "2026-07-10T00:00:01.000Z" },
        { id: "step_3", taskId: "diagnostic_1", sequence: 3, phase: "replanner", status: "completed", payload: { decision: "report", planIndex: 1, planLength: 1, executionFailed: false }, createdAt: "2026-07-10T00:00:02.000Z" }
      ],
      toolCalls: [{
        id: "tool_1", ownerUserId: "user_1", sessionId: null, diagnosticTaskId: "diagnostic_1", toolName: "SearchLog", status: "completed", arguments: {},
        resultSummary: JSON.stringify({ recordCount: 20, records: [{ timestamp: "2026-07-10 08:00:00", level: "ERROR", service: "checkout", event: "timeout", message: "request timeout", latency_ms: 2450 }] }),
        errorMessage: null, startedAt: "2026-07-10T00:00:01.000Z", completedAt: "2026-07-10T00:00:02.000Z", durationMs: 1000, createdAt: "2026-07-10T00:00:01.000Z"
      }],
      evidence: [{ id: "evidence_1", taskId: "diagnostic_1", stepId: "step_2", toolCallId: "tool_1", kind: "log", source: "SearchLog", summary: "RAW_EVIDENCE_MARKER", payload: { raw: "RAW_PAYLOAD_MARKER" }, createdAt: "2026-07-10T00:00:01.000Z" }],
      reports: [{ id: "report_1", title: "Diagnostic report", content: "Persisted report body.", payload: {}, evidenceIds: ["evidence_1"], createdAt: "2026-07-10T00:00:02.000Z" }],
      reportEvidenceLinks: [{ id: "link_1", taskId: "diagnostic_1", reportId: "report_1", evidenceId: "evidence_1", createdAt: "2026-07-10T00:00:02.000Z" }],
      checkpoints: []
    };

    const timeline = mount(AiopsTimeline, { props: { events: [event], isRunning: true } });
    expect(timeline.text()).toContain("诊断过程");
    expect(timeline.text()).toContain("已完成");
    expect(timeline.text()).toContain("SearchLog");
    expect(timeline.text()).not.toContain("raw");
    expect(timeline.text()).not.toContain("x".repeat(400));
    const execution = mount(AiopsEvidenceChain, { props: { chain } });
    expect(execution.text()).toContain("Planner · 生成 1 步诊断计划");
    expect(execution.text()).toContain("Executor · 查询告警窗口日志");
    expect(execution.text()).toContain("Replanner · 证据汇总完成，进入报告");
    expect(execution.text()).toContain("共返回 20 条日志");
    expect(execution.text()).toContain("request timeout");
    expect(execution.findAll("details")).toHaveLength(1);
    expect(execution.get("details").attributes("open")).toBeUndefined();
    expect(execution.text()).not.toContain("recordCount");
    expect(execution.text()).not.toContain("RAW_EVIDENCE_MARKER");
    expect(execution.text()).not.toContain("RAW_PAYLOAD_MARKER");
    expect(execution.text()).not.toContain("evidence_1");
    expect(execution.text()).not.toContain("Persisted report body");
  });

  it("renders a persisted Markdown report as the center reading surface", () => {
    const wrapper = mount(AiopsReportPanel, {
      props: {
        report: {
          id: "report_1",
          title: "告警分析报告",
          content: "# 告警分析报告\n\n## 📋 活跃告警清单\n\n| 告警 | 级别 |\n|---|---|\n| CPU高 | 严重 |\n\n## 📊 结论\n\n需要继续核实。",
          createdAt: "2026-07-10T00:00:02.000Z"
        },
        isRunning: false,
        hasTask: true,
        taskFailed: false
      }
    });

    expect(wrapper.text()).toContain("最终诊断报告");
    expect(wrapper.text()).toContain("已沉淀");
    expect(wrapper.text()).toContain("活跃告警清单");
    expect(wrapper.find("table").exists()).toBe(true);
    expect(wrapper.find(".markdown-content--report").exists()).toBe(true);
  });

  it("explains report generation while a diagnosis is running", () => {
    const wrapper = mount(AiopsReportPanel, {
      props: { report: null, isRunning: true, hasTask: true, taskFailed: false }
    });

    expect(wrapper.text()).toContain("生成中");
    expect(wrapper.text()).toContain("正在等待诊断证据汇总");
  });

  it("lists a server-backed diagnosis case and selects its task", async () => {
    const longSummary = `# 告警分析报告\n\n${"长报告内容".repeat(80)}`;
    const wrapper = mount(AiopsCaseLibrary, {
      props: {
        cases: [{
          id: "case_1", ownerUserId: "user_1", taskId: "diagnostic_1", reportId: "report_1", documentId: "doc_1", indexTaskId: "index_1", alertName: "CheckoutLatencyHigh", service: "checkout", keywords: ["checkout", "latency"], rootCause: "", remediation: "", summary: longSummary, evidenceIds: ["evidence_1"], createdAt: "2026-07-10T00:00:00Z"
        }]
      }
    });

    expect(wrapper.text()).toContain("CheckoutLatencyHigh");
    expect(wrapper.text()).toContain("长报告内容");
    expect(wrapper.text()).not.toContain(longSummary);
    await wrapper.get("button").trigger("click");
    expect(wrapper.emitted("select")).toEqual([["diagnostic_1"]]);
    await wrapper.get('button[title="打开生成的知识文档"]').trigger("click");
    expect(wrapper.emitted("open-document")).toEqual([["doc_1"]]);
  });
});

function diagnostic(): AiopsDiagnosticSummary {
  return {
    id: "diagnostic_1",
    ownerUserId: "user_1",
    status: "succeeded",
    query: "Inspect latency",
    inputPayload: {},
    resultPayload: {},
    createdAt: "2026-07-10T00:00:00.000Z",
    updatedAt: "2026-07-10T00:00:02.000Z",
    completedAt: "2026-07-10T00:00:02.000Z",
    reports: []
  };
}
