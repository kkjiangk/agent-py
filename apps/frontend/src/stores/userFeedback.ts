import { computed, ref } from "vue";
import { defineStore } from "pinia";

import type {
  FeedbackTargetType,
  UpsertFeedbackRequest,
  UserFeedback
} from "@agent-py/api-contracts";

import { createUserFeedbackClient } from "../feedback/userFeedbackClient";
import { toUserFacingError } from "../ui/userFacingError";
import { useFeedbackStore } from "./feedback";

export const useUserFeedbackStore = defineStore("user-feedback", () => {
  const client = createUserFeedbackClient();
  const records = ref<readonly UserFeedback[]>([]);
  const loadedTargets = ref<readonly string[]>([]);
  const pendingKeys = ref<readonly string[]>([]);

  const byKey = computed(() => new Map(records.value.map((item) => [recordKey(item), item])));

  async function ensureLoaded(targetType: FeedbackTargetType, targetId: string): Promise<void> {
    const target = targetKey(targetType, targetId);
    if (loadedTargets.value.includes(target)) return;
    const response = await client.list(targetType, targetId);
    records.value = mergeRecords(records.value, response.items);
    loadedTargets.value = [...loadedTargets.value, target];
  }

  async function upsert(request: UpsertFeedbackRequest): Promise<void> {
    const key = requestKey(request.targetType, request.targetId, request.subjectId);
    pendingKeys.value = [...pendingKeys.value, key];
    try {
      const saved = await client.upsert(request);
      records.value = mergeRecords(records.value, [saved]);
      useFeedbackStore().show("success", "反馈已保存");
    } catch (error) {
      useFeedbackStore().showError(toUserFacingError(error));
      throw error;
    } finally {
      pendingKeys.value = pendingKeys.value.filter((item) => item !== key);
    }
  }

  async function remove(feedbackId: string): Promise<void> {
    await client.delete(feedbackId);
    records.value = records.value.filter((item) => item.id !== feedbackId);
  }

  return {
    byKey,
    pendingKeys,
    ensureLoaded,
    get: (targetType: FeedbackTargetType, targetId: string, subjectId?: string) =>
      byKey.value.get(requestKey(targetType, targetId, subjectId)),
    isPending: (targetType: FeedbackTargetType, targetId: string, subjectId?: string) =>
      pendingKeys.value.includes(requestKey(targetType, targetId, subjectId)),
    remove,
    upsert
  };
});

function targetKey(targetType: FeedbackTargetType, targetId: string): string {
  return `${targetType}:${targetId}`;
}

function requestKey(targetType: FeedbackTargetType, targetId: string, subjectId?: string): string {
  return `${targetKey(targetType, targetId)}:${subjectId ?? ""}`;
}

function recordKey(record: UserFeedback): string {
  return requestKey(record.targetType, record.targetId, record.subjectId ?? undefined);
}

function mergeRecords(
  current: readonly UserFeedback[],
  incoming: readonly UserFeedback[]
): readonly UserFeedback[] {
  const next = new Map(current.map((item) => [recordKey(item), item]));
  incoming.forEach((item) => next.set(recordKey(item), item));
  return [...next.values()];
}
