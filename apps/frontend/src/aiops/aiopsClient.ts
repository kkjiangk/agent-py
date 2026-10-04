import type {
  AiopsDiagnosticCaseListResponse,
  BackgroundJob,
  ActiveAlertListResponse,
  AiopsDiagnosticEvidenceChain,
  AiopsDiagnosticHistoryResponse,
  AiopsDiagnosticSummary,
  CreateAiopsDiagnosticRequest,
  CreateRemediationApprovalRequest,
  DecideRemediationApprovalRequest,
  IngestAlertEventRequest,
  IngestAlertEventResponse,
  RemediationApproval,
  RemediationApprovalListResponse,
  SaveAiopsDiagnosticCaseResponse,
  SseEvent
} from "@agent-py/api-contracts";

import { AUTH_TOKEN_STORAGE_KEY } from "../authClient";
import { createApiClient } from "../api/apiClient";
import { createSseClient } from "../api/sseClient";
import { API_BASE_URL } from "../config";

export interface AiopsClient {
  cancelBackgroundJob?(jobId: string): Promise<BackgroundJob>;
  createDiagnostic(request: CreateAiopsDiagnosticRequest): Promise<AiopsDiagnosticSummary>;
  createRemediationApproval?(
    diagnosticId: string,
    request: CreateRemediationApprovalRequest
  ): Promise<RemediationApproval>;
  decideRemediationApproval?(
    approvalId: string,
    request: DecideRemediationApprovalRequest
  ): Promise<RemediationApproval>;
  ingestAlertEvent?(request: IngestAlertEventRequest): Promise<IngestAlertEventResponse>;
  getEvidenceChain(diagnosticId: string): Promise<AiopsDiagnosticEvidenceChain>;
  listActiveAlerts(): Promise<ActiveAlertListResponse>;
  listDiagnosticCases(): Promise<AiopsDiagnosticCaseListResponse>;
  listDiagnostics(): Promise<AiopsDiagnosticHistoryResponse>;
  listRemediationApprovals?(diagnosticId: string): Promise<RemediationApprovalListResponse>;
  saveDiagnosticCase(diagnosticId: string): Promise<SaveAiopsDiagnosticCaseResponse>;
  streamDiagnostic(diagnosticId: string): AsyncIterable<SseEvent>;
}

export interface CreateAiopsClientOptions {
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof fetch;
  readonly getAccessToken?: () => string | null;
}

export function createAiopsClient(options: CreateAiopsClientOptions = {}): AiopsClient {
  const getAccessToken = options.getAccessToken ?? (() => window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY));
  const transportOptions = {
    baseUrl: options.baseUrl ?? API_BASE_URL,
    ...(options.fetchImpl === undefined ? {} : { fetchImpl: options.fetchImpl }),
    getAccessToken
  };
  const api = createApiClient(transportOptions);
  const sse = createSseClient(transportOptions);

  return {
    cancelBackgroundJob: (jobId) =>
      api.request<BackgroundJob>(`/background-jobs/${jobId}:cancel`, { method: "POST" }),
    createDiagnostic: (request) => api.request<AiopsDiagnosticSummary>("/aiops/diagnostics", {
      body: JSON.stringify(request),
      method: "POST"
    }),
    createRemediationApproval: (diagnosticId, request) =>
      api.request<RemediationApproval>(`/aiops/diagnostics/${diagnosticId}/remediation-approvals`, {
        body: JSON.stringify(request),
        method: "POST"
      }),
    decideRemediationApproval: (approvalId, request) =>
      api.request<RemediationApproval>(`/aiops/remediation-approvals/${approvalId}:decide`, {
        body: JSON.stringify(request),
        method: "POST"
      }),
    getEvidenceChain: (diagnosticId) =>
      api.request<AiopsDiagnosticEvidenceChain>(`/aiops/diagnostics/${diagnosticId}/evidence-chain`),
    ingestAlertEvent: (request) => api.request<IngestAlertEventResponse>("/aiops/alert-events", {
      body: JSON.stringify(request),
      method: "POST"
    }),
    listActiveAlerts: () => api.request<ActiveAlertListResponse>("/aiops/alerts/active"),
    listDiagnosticCases: () => api.request<AiopsDiagnosticCaseListResponse>("/aiops/diagnostic-cases"),
    listDiagnostics: () => api.request<AiopsDiagnosticHistoryResponse>("/aiops/diagnostics"),
    listRemediationApprovals: (diagnosticId) =>
      api.request<RemediationApprovalListResponse>(`/aiops/diagnostics/${diagnosticId}/remediation-approvals`),
    saveDiagnosticCase: (diagnosticId) =>
      api.request<SaveAiopsDiagnosticCaseResponse>(`/aiops/diagnostics/${diagnosticId}:save-to-knowledge`, {
        method: "POST"
      }),
    streamDiagnostic: (diagnosticId) => sse.stream(`/aiops/diagnostics/${diagnosticId}:stream`, { method: "POST" })
  };
}
