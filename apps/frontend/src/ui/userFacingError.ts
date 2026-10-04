import type { ApiErrorMessage } from "@agent-py/api-contracts";

const ERROR_MESSAGES: Readonly<Record<ApiErrorMessage["code"], string>> = {
  CHAT_CONTEXT_LIMIT_REACHED: "上下文已达到 95%，请执行手动压缩后再继续对话。",
  AUTH_INVALID_CREDENTIALS: "邮箱或密码不正确，请重新输入。",
  AUTH_FORBIDDEN: "你没有权限访问该数据。",
  AUTH_SESSION_REVOKED: "登录状态已失效，请重新登录。",
  AUTH_UNAUTHENTICATED: "请先登录后再继续。",
  BUSINESS_CONFLICT: "该数据已经存在或与当前状态冲突，请确认后重试。",
  BUSINESS_NOT_FOUND: "未找到请求的数据，它可能已被删除或你没有访问权限。",
  VALIDATION_INVALID_ARGUMENT: "提交的信息不符合要求，请检查后重试。",
  VALIDATION_MISSING_FIELD: "请补全必填信息后再试。",
  SYSTEM_INTERNAL_ERROR: "系统暂时无法完成该请求，请稍后重试。",
  SYSTEM_UNAVAILABLE: "服务暂时不可用，请稍后重试。"
};

function isApiErrorMessage(value: unknown): value is ApiErrorMessage {
  return value !== null && typeof value === "object" && "code" in value &&
    typeof value.code === "string" && value.code in ERROR_MESSAGES;
}

export function toUserFacingError(error: unknown): string {
  if (error !== null && typeof error === "object" && "error" in error && isApiErrorMessage(error.error)) {
    if (
      typeof error.error.message === "string" &&
      /[\u3400-\u9fff]/u.test(error.error.message)
    ) {
      return error.error.message;
    }
    return ERROR_MESSAGES[error.error.code];
  }
  return "操作未能完成，请稍后重试。";
}
