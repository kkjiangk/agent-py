import type { ToolCallAudit } from "./chat";
import type { BackgroundJob } from "./background-jobs";

export interface KnowledgeBaseSummary {
  readonly id: string;
  readonly name: string;
  readonly ownerUserId: string;
}

export interface KnowledgeBaseListResponse {
  readonly items: readonly KnowledgeBaseSummary[];
}

export interface AiopsDiagnosticSummary {
  readonly id: string;
  readonly ownerUserId: string;
  readonly status: AiopsDiagnosticStatus;
  readonly query: string;
  readonly inputPayload: Record<string, unknown>;
  readonly resultPayload: Record<string, unknown>;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly completedAt: string | null;
  readonly reports: readonly AiopsDiagnosticReport[];
  readonly backgroundJob?: BackgroundJob;
}

export type AiopsDiagnosticStatus = "accepted" | "running" | "succeeded" | "failed" | "cancelled";

export interface CreateAiopsDiagnosticRequest {
  readonly query: string;
  readonly alert?: Record<string, unknown>;
}

export type AlertEventSeverity =
  | "P1"
  | "P2"
  | "P3"
  | "P4"
  | "critical"
  | "high"
  | "medium"
  | "low";

export interface IngestAlertEventRequest {
  readonly schemaVersion?: 1;
  readonly eventId: string;
  readonly incidentId: string;
  readonly service: string;
  readonly severity: AlertEventSeverity;
  readonly alertType: string;
  readonly occurredAt: string;
  readonly payload?: Record<string, unknown>;
}

export interface IngestAlertEventResponse {
  readonly accepted: true;
  readonly eventId: string;
  readonly incidentId: string;
  readonly diagnostic: AiopsDiagnosticSummary;
  readonly broker: {
    readonly topic: string;
    readonly partition: number;
    readonly offset: number;
  };
}

export type RemediationRiskLevel = "low" | "medium" | "high" | "critical";

/** At-least-once Kafka command. Executors must deduplicate commandId before side effects. */
export interface BrokerRemediationCommand {
  readonly schemaVersion: 1;
  readonly commandId: string;
  readonly approvalId: string;
  readonly diagnosticId: string;
  readonly ownerUserId: string;
  readonly toolName: string;
  readonly arguments: Readonly<Record<string, unknown>>;
  readonly riskLevel: RemediationRiskLevel;
  readonly approvedByUserId: string | null;
  readonly approvedAt: string | null;
}
export type RemediationApprovalStatus = "pending" | "approved" | "rejected";
export type RemediationDispatchStatus =
  | "not_dispatched"
  | "not_applicable"
  | "dispatched"
  | "failed";

export interface CreateRemediationApprovalRequest {
  readonly toolName: string;
  readonly arguments?: Record<string, unknown>;
  readonly rationale: string;
  readonly riskLevel: RemediationRiskLevel;
}

export interface DecideRemediationApprovalRequest {
  readonly decision: "approved" | "rejected";
  readonly decisionNote?: string | null;
}

export interface RemediationApproval {
  readonly id: string;
  readonly ownerUserId: string;
  readonly diagnosticId: string;
  readonly toolName: string;
  readonly arguments: Record<string, unknown>;
  readonly rationale: string;
  readonly riskLevel: RemediationRiskLevel;
  readonly status: RemediationApprovalStatus;
  readonly decisionNote: string | null;
  readonly decidedByUserId: string | null;
  readonly decidedAt: string | null;
  readonly dispatchStatus: RemediationDispatchStatus;
  readonly dispatchError: string | null;
  readonly dispatchedAt: string | null;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface RemediationApprovalListResponse {
  readonly items: readonly RemediationApproval[];
}

export interface ActiveAlert {
  readonly id: string;
  readonly source: string;
  readonly alertName: string;
  readonly service: string;
  readonly severity: string;
  readonly status: string;
  readonly startsAt: string;
  readonly summary: string;
  readonly labels: Record<string, string>;
  readonly annotations: Record<string, string>;
  readonly context: Record<string, unknown>;
}

export interface ActiveAlertListResponse {
  readonly items: readonly ActiveAlert[];
}

export interface AiopsDiagnosticReport {
  readonly id: string;
  readonly title: string;
  readonly content: string;
  readonly payload: Record<string, unknown>;
  readonly evidenceIds: readonly string[];
  readonly createdAt: string;
}

export interface AiopsDiagnosticStep {
  readonly id: string;
  readonly taskId: string;
  readonly sequence: number;
  readonly phase: string;
  readonly status: string;
  readonly payload: Record<string, unknown>;
  readonly createdAt: string;
}

export type AiopsEvidenceKind = "log" | "metric" | "alert" | "ticket" | "knowledge_reference";

export interface AiopsDiagnosticEvidence {
  readonly id: string;
  readonly taskId: string;
  readonly stepId: string | null;
  readonly toolCallId: string | null;
  readonly kind: AiopsEvidenceKind;
  readonly source: string;
  readonly summary: string;
  readonly payload: Record<string, unknown>;
  readonly createdAt: string;
}

export interface AiopsReportEvidenceLink {
  readonly id: string;
  readonly taskId: string;
  readonly reportId: string;
  readonly evidenceId: string;
  readonly createdAt: string;
}

export interface AiopsGraphCheckpoint {
  readonly id: string;
  readonly taskId: string;
  readonly threadId: string;
  readonly checkpointNamespace: string;
  readonly checkpointId: string;
  readonly payload: Record<string, unknown>;
  readonly metadata: Record<string, unknown>;
  readonly createdAt: string;
}

export interface AiopsDiagnosticHistoryResponse {
  readonly items: readonly AiopsDiagnosticSummary[];
}

export interface AiopsDiagnosticCase {
  readonly id: string;
  readonly ownerUserId: string;
  readonly taskId: string;
  readonly reportId: string;
  readonly documentId: string;
  readonly indexTaskId: string;
  readonly alertName: string;
  readonly service: string;
  readonly keywords: readonly string[];
  readonly rootCause: string;
  readonly remediation: string;
  readonly summary: string;
  readonly evidenceIds: readonly string[];
  readonly createdAt: string;
}

export interface AiopsDiagnosticCaseListResponse {
  readonly items: readonly AiopsDiagnosticCase[];
}

export interface AiopsDiagnosticEvidenceChain {
  readonly task: AiopsDiagnosticSummary;
  readonly steps: readonly AiopsDiagnosticStep[];
  readonly toolCalls: readonly ToolCallAudit[];
  readonly evidence: readonly AiopsDiagnosticEvidence[];
  readonly reports: readonly AiopsDiagnosticReport[];
  readonly reportEvidenceLinks: readonly AiopsReportEvidenceLink[];
  readonly checkpoints: readonly AiopsGraphCheckpoint[];
}

export interface SaveAiopsDiagnosticCaseResponse {
  readonly document: import("./documents").KnowledgeDocument;
  readonly task: import("./indexing").DocumentIndexTask;
  readonly scheduled: true;
}
