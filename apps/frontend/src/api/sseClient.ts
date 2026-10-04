import type { SseEvent } from "@agent-py/api-contracts";

import {
  ApiClientError,
  buildTransportHeaders,
  readApiError,
  type ApiClientOptions
} from "./apiClient";

export interface SseClient {
  stream(path: string, init?: RequestInit): AsyncIterable<SseEvent>;
}

export function createSseClient(options: ApiClientOptions): SseClient {
  const fetchImpl = options.fetchImpl ?? fetch;
  const baseUrl = options.baseUrl.replace(/\/+$/, "");

  return {
    async *stream(path: string, init: RequestInit = {}): AsyncIterable<SseEvent> {
      const response = await fetchImpl(`${baseUrl}${path}`, {
        ...init,
        headers: buildTransportHeaders({
          accept: "text/event-stream",
          body: init.body,
          headers: init.headers,
          token: options.getAccessToken()
        })
      });
      if (!response.ok) {
        throw new ApiClientError(await readApiError(response), response.status);
      }
      if (response.body === null) {
        throw new ApiClientError({
          code: "SYSTEM_UNAVAILABLE",
          category: "system",
          httpStatus: 503,
          message: "服务暂时不可用，请稍后重试。"
        });
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const parsed = parseSseFrames(buffer);
        buffer = parsed.remainder;
        yield* parsed.events;
      }
      buffer += decoder.decode();
      const parsed = parseSseFrames(buffer);
      yield* parsed.events;
    }
  };
}

function parseSseFrames(buffer: string): {
  readonly events: readonly SseEvent[];
  readonly remainder: string;
} {
  const frames = buffer.split(/\r?\n\r?\n/);
  const remainder = frames.pop() ?? "";
  const events: SseEvent[] = [];
  for (const frame of frames) {
    const data = frame
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice("data:".length).trimStart())
      .join("\n");
    if (data.length === 0) {
      continue;
    }
    try {
      const event: unknown = JSON.parse(data);
      if (!isSseEvent(event)) {
        throw new Error("Invalid shared SSE event.");
      }
      events.push(event);
    } catch {
      throw new ApiClientError({
        code: "SYSTEM_INTERNAL_ERROR",
        category: "system",
        httpStatus: 500,
        message: "系统暂时无法完成该请求，请稍后重试。"
      });
    }
  }
  return { events, remainder };
}

function isSseEvent(value: unknown): value is SseEvent {
  return (
    value !== null &&
    typeof value === "object" &&
    "id" in value &&
    "type" in value &&
    "channel" in value &&
    "timestamp" in value &&
    typeof value.id === "string" &&
    typeof value.type === "string" &&
    typeof value.channel === "string" &&
    typeof value.timestamp === "string"
  );
}
