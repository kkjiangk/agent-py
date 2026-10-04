import { describe, expect, it, vi } from "vitest";

import { createApiClient } from "../src/api/apiClient";
import { createSseClient } from "../src/api/sseClient";

describe("application transport", () => {
  it("attaches the bearer token and unwraps the shared success envelope", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          data: { id: "kb_user_1" },
          meta: { requestId: "req_1" }
        }),
        { headers: { "Content-Type": "application/json" }, status: 200 }
      )
    );
    const client = createApiClient({
      baseUrl: "http://api.test",
      fetchImpl,
      getAccessToken: () => "token_1"
    });

    await expect(client.request<{ id: string }>("/knowledge-bases")).resolves.toEqual({
      id: "kb_user_1"
    });
    const request = fetchImpl.mock.calls[0];
    expect(request?.[0]).toBe("http://api.test/knowledge-bases");
    expect(new Headers(request?.[1]?.headers).get("Authorization")).toBe("Bearer token_1");
  });

  it("normalizes a malformed backend error body into a safe frontend error", async () => {
    const client = createApiClient({
      baseUrl: "http://api.test",
      fetchImpl: vi.fn<typeof fetch>().mockResolvedValue(
        new Response("upstream exploded", { status: 502 })
      ),
      getAccessToken: () => null
    });

    await expect(client.request("/health")).rejects.toMatchObject({
      message: "服务暂时不可用，请稍后重试。",
      status: 502
    });
  });

  it("parses chunked SSE frames as the shared event union", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            'data: {"id":"evt_1","type":"content.delta","channel":"chat",'
          )
        );
        controller.enqueue(encoder.encode('"timestamp":"2026-07-10T00:00:00Z","delta":"Hi","sequence":1}\n\n'));
        controller.close();
      }
    });
    const sse = createSseClient({
      baseUrl: "http://api.test",
      fetchImpl: vi.fn<typeof fetch>().mockResolvedValue(
        new Response(body, { headers: { "Content-Type": "text/event-stream" }, status: 200 })
      ),
      getAccessToken: () => "token_1"
    });
    const events = [];

    for await (const event of sse.stream("/chat/sessions/session_1/messages:stream", {
      body: JSON.stringify({ content: "Hello" }),
      method: "POST"
    })) {
      events.push(event);
    }

    expect(events).toEqual([
      expect.objectContaining({ delta: "Hi", type: "content.delta" })
    ]);
  });
});
