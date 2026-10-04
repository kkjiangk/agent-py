import type { ReferenceSourceSseEvent } from "./sse";

export type ChatMessageRole = "user" | "assistant";

export interface ChatMessageMetadata {
  readonly citations?: readonly ReferenceSourceSseEvent["reference"][];
  readonly reasoning?: readonly string[];
  readonly toolCallIds?: readonly string[];
  readonly custom?: Record<string, unknown>;
}

export interface CreateChatSessionRequest {
  readonly title?: string | null;
}

export type ChatMemoryMode = "every_30_turns" | "context_70_percent" | "manual";

export interface ChatMemoryState {
  readonly mode: ChatMemoryMode;
  readonly contextTokens: number;
  readonly contextWindowTokens: number;
  readonly contextUsagePercent: number;
  readonly compactedMessageCount: number;
  readonly lastCompactedAt: string | null;
  readonly canCompact: boolean;
}

export interface UpdateChatMemoryRequest {
  readonly mode: ChatMemoryMode;
}

export interface ChatSessionSummary {
  readonly id: string;
  readonly ownerUserId: string;
  readonly title: string;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly memory: ChatMemoryState;
}

export interface ChatMessage {
  readonly id: string;
  readonly ownerUserId: string;
  readonly sessionId: string;
  readonly role: ChatMessageRole;
  readonly content: string;
  readonly metadata: ChatMessageMetadata;
  readonly createdAt: string;
}

export interface AppendChatMessageRequest {
  readonly role: ChatMessageRole;
  readonly content: string;
  readonly metadata?: ChatMessageMetadata;
}

export interface StreamChatMessageRequest {
  readonly content: string;
  readonly metadata?: ChatMessageMetadata;
}

export interface ChatSessionListResponse {
  readonly items: readonly ChatSessionSummary[];
}

export interface ChatSessionDetailResponse {
  readonly session: ChatSessionSummary;
  readonly messages: readonly ChatMessage[];
}

export interface ToolCallAudit {
  readonly id: string;
  readonly ownerUserId: string;
  readonly sessionId: string | null;
  readonly diagnosticTaskId: string | null;
  readonly toolName: string;
  readonly status: "started" | "completed" | "failed";
  readonly arguments: Record<string, unknown>;
  readonly resultSummary: string | null;
  readonly errorMessage: string | null;
  readonly startedAt: string;
  readonly completedAt: string | null;
  readonly durationMs: number | null;
  readonly createdAt: string;
}

export interface ChatToolCallAuditListResponse {
  readonly items: readonly ToolCallAudit[];
}

export interface ChatSessionMutationResponse {
  readonly session: ChatSessionSummary;
  readonly message?: ChatMessage;
}

export interface ChatStreamCompleteResult {
  readonly session: ChatSessionSummary;
  readonly message: ChatMessage;
}

export interface ClearChatSessionResponse {
  readonly sessionId: string;
  readonly cleared: true;
  readonly deletedMessages: number;
}

export interface DeleteChatSessionResponse {
  readonly sessionId: string;
  readonly deleted: true;
}
