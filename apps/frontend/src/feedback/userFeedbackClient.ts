import type {
  DeleteFeedbackResponse,
  FeedbackTargetType,
  UpsertFeedbackRequest,
  UserFeedback,
  UserFeedbackListResponse
} from "@agent-py/api-contracts";

import { createApiClient } from "../api/apiClient";
import { AUTH_TOKEN_STORAGE_KEY } from "../authClient";
import { API_BASE_URL } from "../config";

export interface UserFeedbackClient {
  delete(feedbackId: string): Promise<DeleteFeedbackResponse>;
  list(targetType: FeedbackTargetType, targetId: string): Promise<UserFeedbackListResponse>;
  upsert(request: UpsertFeedbackRequest): Promise<UserFeedback>;
}

export function createUserFeedbackClient(): UserFeedbackClient {
  const api = createApiClient({
    baseUrl: API_BASE_URL,
    getAccessToken: () => window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)
  });
  return {
    delete: (feedbackId) =>
      api.request<DeleteFeedbackResponse>(`/feedback/${feedbackId}`, { method: "DELETE" }),
    list: (targetType, targetId) =>
      api.request<UserFeedbackListResponse>(
        `/feedback?targetType=${encodeURIComponent(targetType)}&targetId=${encodeURIComponent(targetId)}`
      ),
    upsert: (request) =>
      api.request<UserFeedback>("/feedback", {
        body: JSON.stringify(request),
        method: "POST"
      })
  };
}
