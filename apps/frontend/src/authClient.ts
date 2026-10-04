import type {
  ApiErrorMessage,
  ApiResponse,
  AuthTokenResponse,
  AuthUser,
  LoginRequest,
  LogoutResponse,
  RegisterRequest
} from "@agent-py/api-contracts";

import { API_BASE_URL } from "./config";

export const AUTH_TOKEN_STORAGE_KEY = "super-ai.auth-token";

export interface AuthClient {
  currentUser(): Promise<AuthUser>;
  login(request: LoginRequest): Promise<AuthTokenResponse>;
  logout(): Promise<void>;
  register(request: RegisterRequest): Promise<AuthTokenResponse>;
}

export interface CreateAuthClientOptions {
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof fetch;
  readonly storage?: Storage;
}

export class AuthClientError extends Error {
  readonly error: ApiErrorMessage;

  constructor(error: ApiErrorMessage) {
    super(error.message);
    this.error = error;
  }
}

export function createAuthClient(options: CreateAuthClientOptions = {}): AuthClient {
  const baseUrl = options.baseUrl ?? API_BASE_URL;
  const fetchImpl = options.fetchImpl ?? fetch;
  const storage = options.storage ?? window.localStorage;

  async function request<TData>(
    path: string,
    init: RequestInit = {},
    optionsForRequest: { readonly persistToken?: boolean } = {}
  ): Promise<TData> {
    const token = storage.getItem(AUTH_TOKEN_STORAGE_KEY);
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json");
    if (init.body !== undefined && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    if (token !== null) {
      headers.set("Authorization", `Bearer ${token}`);
    }

    const response = await fetchImpl(`${baseUrl}${path}`, {
      ...init,
      headers
    });
    if (!response.ok) {
      throw new AuthClientError(await parseApiError(response));
    }

    const payload = (await response.json()) as ApiResponse<TData>;
    if (!payload.ok) {
      throw new AuthClientError(payload.error);
    }
    if (optionsForRequest.persistToken) {
      const tokenResponse = payload.data as AuthTokenResponse;
      storage.setItem(AUTH_TOKEN_STORAGE_KEY, tokenResponse.accessToken);
    }
    return payload.data;
  }

  return {
    currentUser: () => request<AuthUser>("/auth/me"),
    login: (body) =>
      request<AuthTokenResponse>(
        "/auth/login",
        {
          method: "POST",
          body: JSON.stringify(body)
        },
        { persistToken: true }
      ),
    logout: async () => {
      await request<LogoutResponse>("/auth/logout", { method: "POST" });
      storage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    },
    register: (body) =>
      request<AuthTokenResponse>(
        "/auth/register",
        {
          method: "POST",
          body: JSON.stringify(body)
        },
        { persistToken: true }
      )
  };
}

export async function parseApiError(response: Response): Promise<ApiErrorMessage> {
  const payload = (await response.json()) as ApiResponse<unknown>;
  if (!payload.ok) {
    return payload.error;
  }
  return {
    code: "SYSTEM_INTERNAL_ERROR",
    category: "system",
    httpStatus: response.status,
    message: "系统暂时无法完成该请求，请稍后重试。"
  };
}
