import type { AuthTokenResponse, AuthUser, LoginRequest, RegisterRequest } from "@agent-py/api-contracts";

import {
  AUTH_TOKEN_STORAGE_KEY,
  createAuthClient,
  type AuthClient
} from "./authClient";
import { toUserFacingError } from "./ui/userFacingError";

export interface AuthSnapshot {
  readonly errorMessage: string | null;
  readonly isAuthenticated: boolean;
  readonly isLoading: boolean;
  readonly user: AuthUser | null;
}

export interface CreateAuthStateOptions {
  readonly client?: AuthClient;
  readonly storage?: Storage;
}

export interface AuthState {
  initialize(): Promise<void>;
  login(request: LoginRequest): Promise<void>;
  logout(): Promise<void>;
  register(request: RegisterRequest): Promise<void>;
  snapshot(): AuthSnapshot;
}

export function createAuthState(options: CreateAuthStateOptions = {}): AuthState {
  const storage = options.storage ?? window.localStorage;
  const client = options.client ?? createAuthClient({ storage });
  let user: AuthUser | null = null;
  let isLoading = false;
  let errorMessage: string | null = null;

  function applyAuthResult(result: AuthTokenResponse): void {
    user = result.user;
    storage.setItem(AUTH_TOKEN_STORAGE_KEY, result.accessToken);
    errorMessage = null;
  }

  async function runAuthOperation(operation: () => Promise<void>): Promise<void> {
    isLoading = true;
    errorMessage = null;
    try {
      await operation();
    } catch (error) {
      errorMessage = toUserFacingError(error);
      throw error;
    } finally {
      isLoading = false;
    }
  }

  return {
    initialize: async () => {
      const token = storage.getItem(AUTH_TOKEN_STORAGE_KEY);
      if (token === null) {
        return;
      }
      await runAuthOperation(async () => {
        user = await client.currentUser();
      }).catch(() => {
        storage.removeItem(AUTH_TOKEN_STORAGE_KEY);
        user = null;
      });
    },
    login: (request) =>
      runAuthOperation(async () => {
        applyAuthResult(await client.login(request));
      }),
    logout: () =>
      runAuthOperation(async () => {
        await client.logout();
        storage.removeItem(AUTH_TOKEN_STORAGE_KEY);
        user = null;
      }),
    register: (request) =>
      runAuthOperation(async () => {
        applyAuthResult(await client.register(request));
      }),
    snapshot: () => ({
      errorMessage,
      isAuthenticated: user !== null,
      isLoading,
      user
    })
  };
}
