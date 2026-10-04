export type BackgroundJobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface BackgroundJob {
  readonly id: string;
  readonly ownerUserId: string;
  readonly kind: "document_index" | "aiops_diagnosis" | string;
  readonly resourceType: string;
  readonly resourceId: string;
  readonly status: BackgroundJobStatus;
  readonly attempt: number;
  readonly maxAttempts: number;
  readonly timeoutSeconds: number;
  readonly availableAt: string;
  readonly cancelRequestedAt: string | null;
  readonly retryOfJobId: string | null;
  readonly errorMessage: string | null;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly startedAt: string | null;
  readonly completedAt: string | null;
}

export interface BackgroundJobListResponse {
  readonly items: readonly BackgroundJob[];
}
