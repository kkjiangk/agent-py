export type DocumentIndexTaskStatus = "pending" | "running" | "succeeded" | "failed" | "cancelled";

export interface DocumentIndexTask {
  readonly id: string;
  readonly ownerUserId: string;
  readonly knowledgeBaseId: string;
  readonly documentId: string;
  readonly status: DocumentIndexTaskStatus;
  readonly failureReason: string | null;
  readonly retryOfTaskId: string | null;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly startedAt: string | null;
  readonly completedAt: string | null;
}

export interface CreateDocumentIndexTaskResponse {
  readonly task: DocumentIndexTask;
  readonly scheduled: boolean;
}

export interface RetryDocumentIndexTaskResponse {
  readonly task: DocumentIndexTask;
  readonly retriedFromTaskId: string;
  readonly scheduled: boolean;
}
