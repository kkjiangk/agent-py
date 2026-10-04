// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it } from "vitest";

import type { ActiveAlert, AiopsDiagnosticEvidenceChain, AiopsDiagnosticSummary, SseEvent } from "@agent-py/api-contracts";

import type { AiopsClient } from "../src/aiops/aiopsClient";
import ActiveAlertList from "../src/components/ActiveAlertList.vue";
import { setAiopsClientFactoryForTests, useAiopsStore } from "../src/stores/aiops";

const alert: ActiveAlert = {
  id: "fingerprint-checkout-latency",
  source: "local-alertmanager",
  alertName: "CheckoutLatencyHigh",
  service: "checkout",
  severity: "critical",
  status: "active",
  startsAt: "2026-07-10T08:00:00Z",
  summary: "Checkout latency is above the SLO.",
  labels: { alertname: "CheckoutLatencyHigh", service: "checkout" },
  annotations: { summary: "Checkout latency is above the SLO." },
  context: { fingerprint: "fingerprint-checkout-latency" }
};

afterEach(() => setAiopsClientFactoryForTests(null));

describe("active AIOps alerts", () => {
  it("renders alert triage fields and emits the selected alert", async () => {
    const wrapper = mount(ActiveAlertList, { props: { alerts: [alert], errorMessage: null, isLoading: false } });

    expect(wrapper.text()).toContain("CheckoutLatencyHigh");
    expect(wrapper.text()).toContain("checkout");
    expect(wrapper.text()).toContain("Checkout latency is above the SLO.");
    await wrapper.get('button[aria-label="诊断 CheckoutLatencyHigh"]').trigger("click");

    expect(wrapper.emitted("diagnose")?.[0]).toEqual([alert]);
  });

  it("loads real alert data and creates a diagnosis with the selected context", async () => {
    const created: CreateCall[] = [];
    setAiopsClientFactoryForTests(() => fakeClient(created));
    setActivePinia(createPinia());
    const store = useAiopsStore();

    await store.initialize();
    await store.diagnoseAlert(alert);

    expect(store.activeAlerts).toEqual([alert]);
    expect(created[0]?.alert).toMatchObject({
      fingerprint: "fingerprint-checkout-latency",
      alertSource: "local-alertmanager"
    });
    expect(created[0]?.query).toContain("CheckoutLatencyHigh");
  });
});

type CreateCall = { readonly query: string; readonly alert?: Record<string, unknown> };

function fakeClient(created: CreateCall[]): AiopsClient {
  const task: AiopsDiagnosticSummary = {
    id: "diagnostic_1", ownerUserId: "user_1", status: "accepted", query: "Investigate alert", inputPayload: {}, resultPayload: {}, createdAt: "2026-07-10T08:00:00Z", updatedAt: "2026-07-10T08:00:00Z", completedAt: null, reports: []
  };
  const chain: AiopsDiagnosticEvidenceChain = { task, steps: [], toolCalls: [], evidence: [], reports: [], reportEvidenceLinks: [], checkpoints: [] };
  return {
    createDiagnostic: async (request) => { created.push(request); return task; },
    getEvidenceChain: async () => chain,
    listActiveAlerts: async () => ({ items: [alert] }),
    listDiagnosticCases: async () => ({ items: [] }),
    listDiagnostics: async () => ({ items: [] }),
    saveDiagnosticCase: async () => { throw new Error("not used"); },
    streamDiagnostic: async function* (): AsyncIterable<SseEvent> { yield { id: "complete", type: "complete", channel: "aiops", timestamp: "2026-07-10T08:00:02Z" }; }
  };
}
