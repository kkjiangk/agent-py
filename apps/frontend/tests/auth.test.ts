import { describe, expect, it } from "vitest";

import { createAuthClient, parseApiError } from "../src/authClient";
import { createAuthState } from "../src/authState";
import { resolveApiBaseUrl } from "../src/config";

class MemoryStorage implements Storage {
  private readonly values = new Map<string, string>();

  get length(): number {
    return this.values.size;
  }

  clear(): void {
    this.values.clear();
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null;
  }

  key(index: number): string | null {
    return Array.from(this.values.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.values.delete(key);
  }

  setItem(key: string, value: string): void {
    this.values.set(key, value);
  }
}

describe("auth client", () => {
  it("resolves configured API base URL without trailing slashes", () => {
    expect(resolveApiBaseUrl(" http://127.0.0.1:8000/ ")).toBe("http://127.0.0.1:8000");
  });

  it("stores bearer token and sends it on authenticated requests", async () => {
    const requests: RequestInit[] = [];
    const storage = new MemoryStorage();
    const client = createAuthClient({
      baseUrl: "https://api.example.test",
      storage,
      fetchImpl: async (_input, init) => {
        requests.push(init ?? {});
        return new Response(
          JSON.stringify({
            ok: true,
            data: {
              user: {
                id: "user_1",
                email: "timi@example.com",
                displayName: "Timi",
                createdAt: "2026-07-08T00:00:00.000Z"
              },
              accessToken: "token-1",
              tokenType: "bearer"
            },
            meta: { requestId: "req_1" }
          }),
          { status: 200, headers: { "content-type": "application/json" } }
        );
      }
    });

    await client.login({ email: "timi@example.com", password: "correct horse battery staple" });
    await client.currentUser();

    expect(storage.getItem("super-ai.auth-token")).toBe("token-1");
    expect(new Headers(requests[1]?.headers).get("Authorization")).toBe("Bearer token-1");
  });

  it("parses unified API errors", async () => {
    const response = new Response(
      JSON.stringify({
        ok: false,
        error: {
          code: "AUTH_INVALID_CREDENTIALS",
          category: "auth",
          httpStatus: 401,
          message: "Invalid email or password."
        },
        meta: { requestId: "req_2" }
      }),
      { status: 401, headers: { "content-type": "application/json" } }
    );

    await expect(parseApiError(response)).resolves.toMatchObject({
      code: "AUTH_INVALID_CREDENTIALS",
      message: "Invalid email or password."
    });
  });
});

describe("auth state", () => {
  it("loads persisted user and clears state on logout", async () => {
    const storage = new MemoryStorage();
    storage.setItem("super-ai.auth-token", "token-1");
    const state = createAuthState({
      storage,
      client: {
        currentUser: async () => ({
          id: "user_1",
          email: "timi@example.com",
          displayName: "Timi",
          createdAt: "2026-07-08T00:00:00.000Z"
        }),
        login: async () => {
          throw new Error("not used");
        },
        logout: async () => undefined,
        register: async () => {
          throw new Error("not used");
        }
      }
    });

    await state.initialize();
    await state.logout();

    expect(state.snapshot().isAuthenticated).toBe(false);
    expect(state.snapshot().user).toBeNull();
    expect(storage.getItem("super-ai.auth-token")).toBeNull();
  });

  it("tracks registration as authenticated state", async () => {
    const storage = new MemoryStorage();
    const state = createAuthState({
      storage,
      client: {
        currentUser: async () => {
          throw new Error("not used");
        },
        login: async () => {
          throw new Error("not used");
        },
        logout: async () => undefined,
        register: async () => ({
          user: {
            id: "user_1",
            email: "timi@example.com",
            displayName: "Timi",
            createdAt: "2026-07-08T00:00:00.000Z"
          },
          accessToken: "token-1",
          tokenType: "bearer"
        })
      }
    });

    await state.register({
      email: "timi@example.com",
      displayName: "Timi",
      password: "correct horse battery staple"
    });

    expect(state.snapshot().isAuthenticated).toBe(true);
    expect(state.snapshot().user?.displayName).toBe("Timi");
    expect(storage.getItem("super-ai.auth-token")).toBe("token-1");
  });
});
