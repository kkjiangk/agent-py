import { computed, ref } from "vue";
import { defineStore } from "pinia";

import type { AuthTokenResponse, AuthUser, LoginRequest, RegisterRequest } from "@agent-py/api-contracts";

import {
  AUTH_TOKEN_STORAGE_KEY,
  AuthClientError,
  createAuthClient,
  type AuthClient
} from "../authClient";
import { useChatStore } from "./chat";
import { useAiopsStore } from "./aiops";
import { useFeedbackStore } from "./feedback";
import { useKnowledgeStore } from "./knowledge";
import { toUserFacingError } from "../ui/userFacingError";

export const useAuthStore = defineStore("auth", () => {
  const client = createAuthClient();
  const user = ref<AuthUser | null>(null);
  const isInitialized = ref(false);
  const isLoading = ref(false);
  const errorMessage = ref<string | null>(null);
  const isAuthenticated = computed(() => user.value !== null);

  function storage(): Storage {
    return window.localStorage;
  }

  function applyResult(result: AuthTokenResponse): void {
    storage().setItem(AUTH_TOKEN_STORAGE_KEY, result.accessToken);
    user.value = result.user;
    errorMessage.value = null;
  }

  function recordError(error: unknown): void {
    const message = toUserFacingError(error);
    errorMessage.value = message;
    useFeedbackStore().showError(message);
  }

  async function run(operation: () => Promise<void>): Promise<void> {
    isLoading.value = true;
    errorMessage.value = null;
    try {
      await operation();
    } catch (error) {
      recordError(error);
      throw error;
    } finally {
      isLoading.value = false;
    }
  }

  return {
    errorMessage,
    isAuthenticated,
    isInitialized,
    isLoading,
    user,
    initialize: async (): Promise<void> => {
      if (isInitialized.value) {
        return;
      }
      const token = storage().getItem(AUTH_TOKEN_STORAGE_KEY);
      if (token === null) {
        isInitialized.value = true;
        return;
      }
      await run(async () => {
        user.value = await client.currentUser();
      }).catch(() => {
        storage().removeItem(AUTH_TOKEN_STORAGE_KEY);
        user.value = null;
        useChatStore().reset();
        useKnowledgeStore().reset();
        useAiopsStore().reset();
      });
      isInitialized.value = true;
    },
    login: (request: LoginRequest): Promise<void> =>
      run(async () => {
        applyResult(await client.login(request));
      }),
    logout: (): Promise<void> =>
      run(async () => {
        try {
          await client.logout();
        } finally {
          storage().removeItem(AUTH_TOKEN_STORAGE_KEY);
          user.value = null;
          useChatStore().reset();
          useKnowledgeStore().reset();
          useAiopsStore().reset();
        }
      }),
    register: (request: RegisterRequest): Promise<void> =>
      run(async () => {
        applyResult(await client.register(request));
      })
  };
});

export function createAuthRouteAccess(store: ReturnType<typeof useAuthStore>): {
  initialize(): Promise<void>;
  isAuthenticated(): boolean;
} {
  return {
    initialize: () => store.initialize(),
    isAuthenticated: () => store.isAuthenticated
  };
}
