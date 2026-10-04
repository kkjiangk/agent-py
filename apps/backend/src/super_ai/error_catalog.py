"""Shared API and SSE error catalog."""

ERROR_DEFINITIONS = {
    "CHAT_CONTEXT_LIMIT_REACHED": (
        "business",
        409,
        "上下文已达到 95%，请执行手动压缩后再继续对话。",
    ),
    "AUTH_FORBIDDEN": ("auth", 403, "You do not have permission to access this resource."),
    "AUTH_INVALID_CREDENTIALS": ("auth", 401, "Invalid credentials."),
    "AUTH_SESSION_REVOKED": ("auth", 401, "The authentication session has been revoked."),
    "AUTH_UNAUTHENTICATED": ("auth", 401, "Authentication is required."),
    "BUSINESS_CONFLICT": (
        "business",
        409,
        "The requested operation conflicts with the current resource state.",
    ),
    "BUSINESS_NOT_FOUND": ("business", 404, "The requested resource was not found."),
    "VALIDATION_INVALID_ARGUMENT": ("validation", 400, "The request parameters are invalid."),
    "VALIDATION_MISSING_FIELD": ("validation", 422, "A required field is missing."),
    "SYSTEM_INTERNAL_ERROR": ("system", 500, "The system could not complete the request."),
    "SYSTEM_UNAVAILABLE": ("system", 503, "The system is temporarily unavailable."),
}
