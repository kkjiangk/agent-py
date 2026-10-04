import { createPinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  ChatMessage,
  ChatSessionSummary,
  SseEvent,
  ToolCallAudit
} from "@agent-py/api-contracts";

import {
  CHAT_TYPEWRITER_DELAY_MS,
  setChatClientFactoryForTests,
  useChatStore
} from "../src/stores/chat";
import type { ChatClient } from "../src/chat/chatClient";

const session = (overrides: Partial<ChatSessionSummary> = {}): ChatSessionSummary => ({
  id: "chat_1",
  ownerUserId: "user_1",
  title: "Restart API",
  createdAt: "2026-07-10T00:00:00.000Z",
  updatedAt: "2026-07-10T00:01:00.000Z",
  memory: {
    mode: "every_30_turns",
    contextTokens: 1200,
    contextWindowTokens: 131072,
    contextUsagePercent: 0.9,
    compactedMessageCount: 0,
    lastCompactedAt: null,
    canCompact: true
  },
  ...overrides
});

const message = (overrides: Partial<ChatMessage> = {}): ChatMessage => ({
  id: "message_1",
  ownerUserId: "user_1",
  sessionId: "chat_1",
  role: "assistant",
  content: "Use the **runbook**.",
  metadata: {},
  createdAt: "2026-07-10T00:01:00.000Z",
  ...overrides
});

const audit = (): ToolCallAudit => ({
  id: "tool_1",
  ownerUserId: "user_1",
  sessionId: "chat_1",
  diagnosticTaskId: null,
  toolName: "knowledge_retrieval",
  status: "completed",
  arguments: { query: "restart api" },
  resultSummary: "Found 1 relevant chunk.",
  errorMessage: null,
  startedAt: "2026-07-10T00:00:01.000Z",
  completedAt: "2026-07-10T00:00:02.000Z",
  durationMs: 18,
  createdAt: "2026-07-10T00:00:01.000Z"
});

afterEach(() => {
  vi.useRealTimers();
  setChatClientFactoryForTests(null);
});

describe("chat store", () => {
  it("loads session history from the backend when a user selects a conversation", async () => {
    setChatClientFactoryForTests(() => fakeClient());
    setActivePinia(createPinia());
    const store = useChatStore();

    await store.initialize();
    await store.selectSession("chat_1");

    expect(store.sessions).toEqual([session()]);
    expect(store.activeSessionId).toBe("chat_1");
    expect(store.messages).toEqual([message()]);
    expect(store.toolAudits).toEqual([audit()]);
  });

  it("reconciles streamed content, references, and tool calls with persisted history", async () => {
    const streamed: SseEvent[] = [
      {
        id: "event_1",
        type: "tool.call",
        channel: "chat",
        timestamp: "2026-07-10T00:00:01.000Z",
        toolCall: {
          id: "tool_1",
          name: "knowledge_retrieval",
          status: "started",
          input: { query: "restart api" }
        }
      },
      {
        id: "event_2",
        type: "content.delta",
        channel: "chat",
        timestamp: "2026-07-10T00:00:01.000Z",
        delta: "Use the ",
        sequence: 1
      },
      {
        id: "event_3",
        type: "reference.source",
        channel: "chat",
        timestamp: "2026-07-10T00:00:02.000Z",
        reference: {
          id: "reference_1",
          title: "Restart runbook",
          sourceType: "document",
          documentId: "doc_1",
          chunkId: "chunk_1",
          score: 0.94
        }
      },
      {
        id: "event_4",
        type: "tool.call",
        channel: "chat",
        timestamp: "2026-07-10T00:00:02.000Z",
        toolCall: {
          id: "tool_1",
          name: "knowledge_retrieval",
          status: "completed",
          output: { results: 1 }
        }
      },
      {
        id: "event_5",
        type: "complete",
        channel: "chat",
        timestamp: "2026-07-10T00:00:03.000Z",
        result: {
          session: session(),
          message: message({
            metadata: {
              citations: [
                {
                  id: "reference_1",
                  title: "Restart runbook",
                  sourceType: "document",
                  documentId: "doc_1",
                  chunkId: "chunk_1",
                  score: 0.94
                }
              ],
              toolCallIds: ["tool_1"]
            }
          })
        }
      }
    ];
    setChatClientFactoryForTests(() => fakeClient({ streamed }));
    setActivePinia(createPinia());
    const store = useChatStore();

    await store.initialize();
    await store.selectSession("chat_1");
    await store.send("How do I restart the API?");

    expect(store.isSending).toBe(false);
    expect(store.messages).toEqual([
      message({
        metadata: {
          citations: [
            {
              id: "reference_1",
              title: "Restart runbook",
              sourceType: "document",
              documentId: "doc_1",
              chunkId: "chunk_1",
              score: 0.94
            }
          ],
          toolCallIds: ["tool_1"]
        }
      })
    ]);
    expect(store.references).toEqual([
      expect.objectContaining({ id: "reference_1", title: "Restart runbook" })
    ]);
    expect(store.toolAudits).toEqual([audit()]);
    expect(store.liveToolCalls).toEqual([]);
  });

  it("sorts live references by rerank score and keeps only five", async () => {
    const references: SseEvent[] = [0.42, 0.98, 0.61, 0.75, 0.88, 0.53].map(
      (rerankScore, index) => ({
        id: `event_ref_${index}`,
        type: "reference.source",
        channel: "chat",
        timestamp: "2026-07-10T00:00:02.000Z",
        reference: {
          id: `reference_${index}`,
          title: `Source ${index}`,
          sourceType: "knowledge-base",
          score: rerankScore,
          vectorScore: 0.9 - index / 100,
          rerankScore
        }
      })
    );
    references.push({
      id: "event_complete",
      type: "complete",
      channel: "chat",
      timestamp: "2026-07-10T00:00:03.000Z",
      result: {
        session: session(),
        message: message({
          metadata: {
            citations: references.flatMap((event) =>
              event.type === "reference.source" ? [event.reference] : []
            )
          }
        })
      }
    });
    setChatClientFactoryForTests(() => fakeClient({ streamed: references }));
    setActivePinia(createPinia());
    const store = useChatStore();

    await store.initialize();
    await store.selectSession("chat_1");
    await store.send("rank sources");

    expect(store.references.map((reference) => reference.rerankScore)).toEqual([
      0.98,
      0.88,
      0.75,
      0.61,
      0.53
    ]);
  });

  it("clears the previous turn references as soon as a new turn starts", async () => {
    let releaseStream: (() => void) | undefined;
    const streamGate = new Promise<void>((resolve) => {
      releaseStream = resolve;
    });
    const previousAnswer = message({
      metadata: {
        citations: [
          {
            id: "old_reference",
            title: "Old runbook",
            sourceType: "knowledge-base",
            score: 0.91
          }
        ]
      }
    });
    const client = fakeClient({ historyMessage: previousAnswer });
    let latestTurnCompleted = false;
    client.getSession = async () => ({
      session: session(),
      messages: [latestTurnCompleted ? message({ metadata: {} }) : previousAnswer]
    });
    client.streamMessage = async function* (): AsyncIterable<SseEvent> {
      await streamGate;
      latestTurnCompleted = true;
      yield {
        id: "event_complete_new_turn",
        type: "complete",
        channel: "chat",
        timestamp: "2026-07-10T00:00:03.000Z",
        result: { session: session(), message: message({ metadata: {} }) }
      };
    };
    setChatClientFactoryForTests(() => client);
    setActivePinia(createPinia());
    const store = useChatStore();
    await store.initialize();
    expect(store.references.map((reference) => reference.id)).toEqual(["old_reference"]);

    const sending = store.send("new question");
    await Promise.resolve();

    expect(store.references).toEqual([]);
    releaseStream?.();
    await sending;
    expect(store.references).toEqual([]);
  });

  it("renders model content one character per typewriter tick", async () => {
    vi.useFakeTimers();
    const streamed: SseEvent[] = [
      {
        id: "event_content_typewriter",
        type: "content.delta",
        channel: "chat",
        timestamp: "2026-07-10T00:00:01.000Z",
        delta: "ABC",
        sequence: 1
      },
      {
        id: "event_complete_typewriter",
        type: "complete",
        channel: "chat",
        timestamp: "2026-07-10T00:00:02.000Z",
        result: {
          session: session(),
          message: message({ content: "ABC" })
        }
      }
    ];
    setChatClientFactoryForTests(() => fakeClient({ streamed }));
    setActivePinia(createPinia());
    const store = useChatStore();
    await store.initialize();

    const sending = store.send("type slowly");
    await Promise.resolve();
    await Promise.resolve();
    const draftContent = (): string | undefined =>
      store.messages.find((item) => item.id.startsWith("message_draft_"))?.content;

    expect(draftContent()).toBe("A");
    await vi.advanceTimersByTimeAsync(CHAT_TYPEWRITER_DELAY_MS);
    expect(draftContent()).toBe("AB");
    await vi.advanceTimersByTimeAsync(CHAT_TYPEWRITER_DELAY_MS);
    expect(draftContent()).toBe("ABC");
    await vi.advanceTimersByTimeAsync(CHAT_TYPEWRITER_DELAY_MS);
    await sending;
    expect(store.messages[0]?.content).toBe("ABC");
  });

  it("clears visible conversation state on logout without deleting server sessions", async () => {
    setChatClientFactoryForTests(() => fakeClient());
    setActivePinia(createPinia());
    const store = useChatStore();
    await store.initialize();
    await store.selectSession("chat_1");

    store.reset();

    expect(store.sessions).toEqual([]);
    expect(store.messages).toEqual([]);
    expect(store.activeSessionId).toBeNull();
  });

  it("updates and compacts memory for only the active session", async () => {
    setChatClientFactoryForTests(() => fakeClient());
    setActivePinia(createPinia());
    const store = useChatStore();
    await store.initialize();

    await store.updateMemoryMode("manual");
    expect(store.activeSession?.memory.mode).toBe("manual");

    await store.compactMemory();
    expect(store.activeSession?.memory.contextUsagePercent).toBe(0.2);
    expect(store.isUpdatingMemory).toBe(false);
  });
});

function fakeClient(
  options: {
    readonly historyMessage?: ChatMessage;
    readonly streamed?: readonly SseEvent[];
  } = {}
): ChatClient {
  let persistedMessage = options.historyMessage ?? message();
  return {
    createSession: async () => session({ id: "chat_new", title: "New chat" }),
    deleteSession: async (sessionId) => ({ sessionId, deleted: true }),
    getSession: async () => ({
      session: session(),
      messages: [persistedMessage]
    }),
    listSessions: async () => ({ items: [session()] }),
    listToolCallAudits: async () => ({ items: [audit()] }),
    updateMemoryMode: async (_sessionId, mode) => session({ memory: { ...session().memory, mode } }),
    compactMemory: async () => session({ memory: { ...session().memory, contextUsagePercent: 0.2 } }),
    streamMessage: async function* (): AsyncIterable<SseEvent> {
      for (const event of options.streamed ?? []) {
        if (event.type === "complete" && event.channel === "chat") {
          const result = event.result as { readonly message?: ChatMessage };
          if (result.message !== undefined) persistedMessage = result.message;
        }
        yield event;
      }
    }
  };
}
