import { describe, expect, it } from "vitest";

import {
  describeSharedContractUsage,
  getFrontendFoundationHealth,
  getRequiredSseEventTypes
} from "../src/foundation";

describe("frontend contract consumption", () => {
  it("uses shared API response contracts", () => {
    const usage = describeSharedContractUsage();

    expect(usage.ok).toBe(true);
    expect(usage.data.service).toBe(getFrontendFoundationHealth().service);
    expect(usage.meta.requestId).toBe("frontend-foundation");
  });

  it("uses shared SSE event contracts", () => {
    expect(getRequiredSseEventTypes()).toEqual([
      "content.delta",
      "reasoning.delta",
      "tool.call",
      "reference.source",
      "task.status",
      "report",
      "complete",
      "error"
    ]);
  });
});
