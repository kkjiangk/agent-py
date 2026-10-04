import type { ApiErrorCode, ApiErrorMessage, ApiResponse } from "@agent-py/api-contracts";

export interface ApiClientOptions {
  readonly baseUrl: string;
  readonly fetchImpl?: typeof fetch;
  readonly getAccessToken: () => string | null;
}

export interface TypedApiClient {
  request<TData>(path: string, init?: RequestInit): Promise<TData>;
}

export class ApiClientError extends Error {
  readonly error: ApiErrorMessage;
  readonly status: number;

  constructor(error: ApiErrorMessage, status = error.httpStatus) {
    super(error.message);
    this.name = "ApiClientError";
    this.error = error;
    this.status = status;
  }
}

export function createApiClient(options: ApiClientOptions): TypedApiClient {
  const fetchImpl = options.fetchImpl ?? fetch;
  const baseUrl = options.baseUrl.replace(/\/+$/, "");

  return {
    async request<TData>(path: string, init: RequestInit = {}): Promise<TData> {
      const response = await fetchImpl(`${baseUrl}${path}`, {
        ...init,
        headers: buildTransportHeaders({
          accept: "application/json",
          body: init.body,
          headers: init.headers,
          token: options.getAccessToken()
        })
      });
      const payload = await readResponseEnvelope<TData>(response);
      if (!payload.ok) {
        throw new ApiClientError(payload.error, response.status);
      }
      return payload.data;
    }
  };
}

export function buildTransportHeaders(options: {
  readonly accept: string;
  readonly body?: BodyInit | null | undefined;
  readonly headers?: HeadersInit | undefined;
  readonly token: string | null;
}): Record<string, string> {
  const headers = new Headers(options.headers);
  if (!headers.has("Accept")) {
    headers.set("Accept", options.accept);
  }
  if (options.body !== undefined && options.body !== null && !isFormData(options.body) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (options.token !== null) {
    headers.set("Authorization", `Bearer ${options.token}`);
  }
  return Object.fromEntries(headers.entries());
}

export async function readApiError(response: Response): Promise<ApiErrorMessage> {
  const payload = await readResponseEnvelope<unknown>(response).catch(() => null);
  if (payload !== null && !payload.ok) {
    return payload.error;
  }
  return fallbackError(response.status);
}

async function readResponseEnvelope<TData>(response: Response): Promise<ApiResponse<TData>> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    if (!response.ok) {
      throw new ApiClientError(fallbackError(response.status), response.status);
    }
    throw new ApiClientError(fallbackError(500), response.status);
  }
  if (!isApiResponse<TData>(payload)) {
    throw new ApiClientError(fallbackError(response.status), response.status);
  }
  return payload;
}

function isApiResponse<TData>(value: unknown): value is ApiResponse<TData> {
  if (value === null || typeof value !== "object" || !("ok" in value)) {
    return false;
  }
  if (value.ok === true) {
    return "data" in value;
  }
  return value.ok === false && "error" in value && isApiErrorMessage(value.error);
}

function isApiErrorMessage(value: unknown): value is ApiErrorMessage {
  return (
    value !== null &&
    typeof value === "object" &&
    "code" in value &&
    "category" in value &&
    "httpStatus" in value &&
    "message" in value &&
    typeof value.code === "string" &&
    typeof value.category === "string" &&
    typeof value.httpStatus === "number" &&
    typeof value.message === "string"
  );
}

function isFormData(value: BodyInit): value is FormData {
  return typeof FormData !== "undefined" && value instanceof FormData;
}

function fallbackError(status: number): ApiErrorMessage {
  const unavailable = status >= 500;
  return {
    code: (unavailable ? "SYSTEM_UNAVAILABLE" : "SYSTEM_INTERNAL_ERROR") as ApiErrorCode,
    category: "system",
    httpStatus: status,
    message: unavailable
      ? "服务暂时不可用，请稍后重试。"
      : "系统暂时无法完成该请求，请稍后重试。"
  };
}
