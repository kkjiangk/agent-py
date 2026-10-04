import { API_ERROR_CODES, type ApiErrorCategory, type ApiErrorCode } from "./errors";

export interface ApiResponseMeta {
  readonly requestId: string;
  readonly traceId?: string;
}

export interface ApiErrorDetail {
  readonly code: string;
  readonly message: string;
  readonly path?: readonly string[];
}

export interface ApiErrorMessage {
  readonly code: ApiErrorCode;
  readonly category: ApiErrorCategory;
  readonly httpStatus: number;
  readonly message: string;
  readonly details?: readonly ApiErrorDetail[];
}

export interface ApiSuccessResponse<TData> {
  readonly ok: true;
  readonly data: TData;
  readonly meta: ApiResponseMeta;
}

export interface ApiErrorResponse {
  readonly ok: false;
  readonly error: ApiErrorMessage;
  readonly meta: ApiResponseMeta;
}

export type ApiResponse<TData> = ApiSuccessResponse<TData> | ApiErrorResponse;

export function buildSuccessResponse<TData>(
  data: TData,
  meta: ApiResponseMeta
): ApiSuccessResponse<TData> {
  return {
    ok: true,
    data,
    meta
  };
}

export function buildErrorResponse(
  code: ApiErrorCode,
  options: ApiResponseMeta & {
    readonly details?: readonly ApiErrorDetail[];
    readonly message?: string;
  }
): ApiErrorResponse {
  const definition = API_ERROR_CODES[code];

  return {
    ok: false,
    error: {
      code,
      category: definition.category,
      httpStatus: definition.httpStatus,
      message: options.message ?? definition.message,
      ...(options.details ? { details: options.details } : {})
    },
    meta: {
      requestId: options.requestId,
      ...(options.traceId ? { traceId: options.traceId } : {})
    }
  };
}
