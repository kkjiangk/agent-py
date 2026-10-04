import { ref } from "vue";
import { defineStore } from "pinia";

import type {
  ActiveAlert,
  AiopsDiagnosticCase,
  AiopsDiagnosticEvidenceChain,
  AiopsDiagnosticSummary,
  CreateAiopsDiagnosticRequest,
  SseEvent
} from "@agent-py/api-contracts";

import { ApiClientError } from "../api/apiClient";
import { createAiopsClient, type AiopsClient } from "../aiops/aiopsClient";
import { useFeedbackStore } from "./feedback";
import { toUserFacingError } from "../ui/userFacingError";

let clientFactory: () => AiopsClient = createAiopsClient;

export function setAiopsClientFactoryForTests(factory: (() => AiopsClient) | null): void {
  clientFactory = factory ?? createAiopsClient;
}

export const useAiopsStore = defineStore("aiops", () => {
  const client = clientFactory();
  const history = ref<readonly AiopsDiagnosticSummary[]>([]);
  const activeAlerts = ref<readonly ActiveAlert[]>([]);
  const diagnosticCases = ref<readonly AiopsDiagnosticCase[]>([]);
  const alertsErrorMessage = ref<string | null>(null);
  const alertsLoading = ref(false);
  const activeDiagnosticId = ref<string | null>(null);
  const activeTask = ref<AiopsDiagnosticSummary | null>(null);
  const evidenceChain = ref<AiopsDiagnosticEvidenceChain | null>(null);
  const liveEvents = ref<readonly SseEvent[]>([]);
  const isLoading = ref(false);
  const isRunning = ref(false);
  const errorMessage = ref<string | null>(null);
  const savedCaseDocumentId = ref<string | null>(null);

  function reportError(error: unknown): void {
    const message = toUserFacingError(error);
    errorMessage.value = message;
    useFeedbackStore().showError(message);
  }

  function upsertHistory(task: AiopsDiagnosticSummary): void {
    history.value = [task, ...history.value.filter((item) => item.id !== task.id)]
      .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
  }

  async function reloadHistory(): Promise<void> {
    history.value = (await client.listDiagnostics()).items;
  }

  async function reloadActiveAlerts(): Promise<void> {
    alertsLoading.value = true;
    alertsErrorMessage.value = null;
    try {
      activeAlerts.value = (await client.listActiveAlerts()).items;
    } catch (error) {
      activeAlerts.value = [];
      alertsErrorMessage.value = "暂时无法获取活跃告警。";
    } finally {
      alertsLoading.value = false;
    }
  }

  async function reloadDiagnosticCases(): Promise<void> {
    diagnosticCases.value = (await client.listDiagnosticCases()).items;
  }

  async function loadEvidenceChain(diagnosticId: string): Promise<void> {
    const chain = await client.getEvidenceChain(diagnosticId);
    evidenceChain.value = chain;
    activeDiagnosticId.value = chain.task.id;
    activeTask.value = chain.task;
    upsertHistory(chain.task);
  }

  function reset(): void {
    history.value = [];
    activeAlerts.value = [];
    diagnosticCases.value = [];
    alertsErrorMessage.value = null;
    alertsLoading.value = false;
    activeDiagnosticId.value = null;
    activeTask.value = null;
    evidenceChain.value = null;
    liveEvents.value = [];
    isLoading.value = false;
    isRunning.value = false;
    errorMessage.value = null;
    savedCaseDocumentId.value = null;
  }

  async function runDiagnostic(
    query: string,
    alert?: Record<string, unknown>,
  ): Promise<void> {
    const request: CreateAiopsDiagnosticRequest = {
      query,
      ...(alert === undefined ? {} : { alert })
    };
    isRunning.value = true;
    errorMessage.value = null;
    liveEvents.value = [];
    evidenceChain.value = null;
    try {
      const created = await client.createDiagnostic(request);
      activeDiagnosticId.value = created.id;
      activeTask.value = created;
      upsertHistory(created);
      for await (const event of client.streamDiagnostic(created.id)) {
        liveEvents.value = [...liveEvents.value, event];
        if (event.type === "error") {
          reportError(new ApiClientError(event.error));
        }
      }
      await Promise.all([loadEvidenceChain(created.id), reloadHistory(), reloadDiagnosticCases()]);
    } catch (error) {
      reportError(error);
      try {
        if (activeDiagnosticId.value !== null) {
            await Promise.all([
              loadEvidenceChain(activeDiagnosticId.value),
              reloadHistory(),
              reloadDiagnosticCases()
            ]);
        }
      } catch (reconciliationError) {
        reportError(reconciliationError);
      }
    } finally {
      isRunning.value = false;
    }
  }

  async function diagnoseAlert(alert: ActiveAlert): Promise<void> {
    const query = `排查活跃告警：${alert.alertName}，服务：${alert.service}，级别：${alert.severity}。${alert.summary}`;
    await runDiagnostic(query, {
      ...alert.context,
      alertSource: alert.source,
      alertName: alert.alertName,
      service: alert.service,
      severity: alert.severity,
      status: alert.status,
      startsAt: alert.startsAt
    });
  }

  return {
    activeDiagnosticId,
    activeAlerts,
    activeTask,
    diagnosticCases,
    alertsErrorMessage,
    alertsLoading,
    errorMessage,
    evidenceChain,
    history,
    isLoading,
    isRunning,
    liveEvents,
    savedCaseDocumentId,
    initialize: async (): Promise<void> => {
      isLoading.value = true;
      errorMessage.value = null;
      try {
        await reloadHistory();
      } catch (error) {
        reset();
        reportError(error);
        throw error;
      } finally {
        isLoading.value = false;
      }
      await Promise.all([reloadActiveAlerts(), reloadDiagnosticCases().catch(() => undefined)]);
    },
    selectDiagnostic: async (diagnosticId: string): Promise<void> => {
      isLoading.value = true;
      errorMessage.value = null;
      liveEvents.value = [];
      try {
        await loadEvidenceChain(diagnosticId);
      } catch (error) {
        evidenceChain.value = null;
        reportError(error);
        throw error;
      } finally {
        isLoading.value = false;
      }
    },
    diagnoseAlert,
    refreshActiveAlerts: reloadActiveAlerts,
    refreshDiagnosticCases: reloadDiagnosticCases,
    runDiagnostic,
    cancelActive: async (): Promise<void> => {
      const jobId = activeTask.value?.backgroundJob?.id;
      if (jobId === undefined || client.cancelBackgroundJob === undefined) return;
      try {
        await client.cancelBackgroundJob(jobId);
        isRunning.value = false;
        await Promise.all([reloadHistory(), loadEvidenceChain(activeTask.value!.id)]);
      } catch (error) {
        reportError(error);
        throw error;
      }
    },
    saveActiveCase: async (): Promise<void> => {
      if (activeDiagnosticId.value === null) return;
      try {
        const saved = await client.saveDiagnosticCase(activeDiagnosticId.value);
        savedCaseDocumentId.value = saved.document.id;
      } catch (error) {
        reportError(error);
        throw error;
      }
    },
    reset
  };
});
