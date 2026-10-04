export type FeedbackTargetType =
  | "chat_message"
  | "citation"
  | "diagnostic_step"
  | "diagnostic_report";
export type FeedbackRating = "positive" | "negative";

export interface UserFeedback {
  readonly id: string;
  readonly ownerUserId: string;
  readonly targetType: FeedbackTargetType;
  readonly targetId: string;
  readonly subjectId: string | null;
  readonly rating: FeedbackRating;
  readonly reason: string | null;
  readonly comment: string | null;
  readonly correction: string | null;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface UpsertFeedbackRequest {
  readonly targetType: FeedbackTargetType;
  readonly targetId: string;
  readonly subjectId?: string;
  readonly rating: FeedbackRating;
  readonly reason?: string;
  readonly comment?: string;
  readonly correction?: string;
}

export interface UserFeedbackListResponse {
  readonly items: readonly UserFeedback[];
}

export interface DeleteFeedbackResponse {
  readonly deleted: true;
  readonly feedbackId: string;
}
