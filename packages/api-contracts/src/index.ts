export interface HealthContract {
  readonly service: string;
  readonly status: "ok";
  readonly version: string;
}

export const FOUNDATION_HEALTH_CONTRACT = {
  service: "super-ai-backend",
  status: "ok",
  version: "0.1.0"
} as const satisfies HealthContract;

export * from "./auth";
export * from "./background-jobs";
export * from "./chat";
export * from "./chat-configuration";
export * from "./documents";
export * from "./errors";
export * from "./feedback";
export * from "./indexing";
export * from "./mcp";
export * from "./openapi";
export * from "./protected-data";
export * from "./retrieval";
export * from "./responses";
export * from "./sse";
export * from "./vector";
