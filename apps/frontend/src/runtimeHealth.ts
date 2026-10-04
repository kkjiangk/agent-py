import { createApiClient, type ApiClientOptions } from "./api/apiClient";
import { AUTH_TOKEN_STORAGE_KEY } from "./authClient";
import { API_BASE_URL } from "./config";

export interface RuntimeHealth {
  readonly service: string;
  readonly status: "ok";
  readonly version: string;
}

export function createRuntimeHealthClient(options?: Partial<ApiClientOptions>): { health(): Promise<RuntimeHealth> } {
  const api = createApiClient({
    baseUrl: options?.baseUrl ?? API_BASE_URL,
    ...(options?.fetchImpl === undefined ? {} : { fetchImpl: options.fetchImpl }),
    getAccessToken: options?.getAccessToken ?? (() => window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY))
  });
  return { health: () => api.request<RuntimeHealth>("/health") };
}
