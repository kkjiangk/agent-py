import {
  FOUNDATION_HEALTH_CONTRACT,
  SSE_EVENT_TYPES,
  buildSuccessResponse,
  type ApiSuccessResponse,
  type HealthContract,
  type SseEventType
} from "@agent-py/api-contracts";

export function getFrontendFoundationHealth(): HealthContract {
  return FOUNDATION_HEALTH_CONTRACT;
}

export function buildHealthMessage(contract: HealthContract): string {
  return `${contract.service} ${contract.version} is ${contract.status}`;
}

export function describeSharedContractUsage(): ApiSuccessResponse<HealthContract> {
  return buildSuccessResponse(FOUNDATION_HEALTH_CONTRACT, {
    requestId: "frontend-foundation"
  });
}

export function getRequiredSseEventTypes(): readonly SseEventType[] {
  return SSE_EVENT_TYPES;
}
