"""Secret-safe structured logging and request correlation helpers."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from contextvars import ContextVar, Token
from time import monotonic
from typing import cast

_request_id: ContextVar[str | None] = ContextVar("super_ai_request_id", default=None)
_STRUCTURED_HANDLER_NAME = "super_ai_structured_events"
_SENSITIVE_KEYS = {
    "access_token",
    "accesstoken",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "credentials",
    "key",
    "password",
    "secret",
    "secret_id",
    "secret_key",
    "secretid",
    "secretkey",
    "token",
}


def set_request_id(request_id: str) -> Token[str | None]:
    """Set the active request correlation id for the current async context."""
    return _request_id.set(request_id)


def configure_structured_logging() -> None:
    """Ensure local runtime emits structured events through its own logger namespace."""
    logger = logging.getLogger("super_ai")
    logger.disabled = False
    logger.setLevel(logging.INFO)
    for name, configured_logger in logger.manager.loggerDict.items():
        if name.startswith("super_ai.") and isinstance(configured_logger, logging.Logger):
            configured_logger.disabled = False
    if any(handler.get_name() == _STRUCTURED_HANDLER_NAME for handler in logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.set_name(_STRUCTURED_HANDLER_NAME)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous request correlation context."""
    _request_id.reset(token)


def emit_event(logger: logging.Logger, event: str, **fields: object) -> None:
    """Emit one compact JSON event without raw request or provider payloads."""
    payload: dict[str, object] = {"event": event}
    request_id = _request_id.get()
    if request_id is not None:
        payload["requestId"] = request_id
    payload.update(fields)
    encoded = json.dumps(
        _redact(payload),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    logger.info(encoded)


def elapsed_ms(started_at: float) -> float:
    """Return an elapsed duration suitable for a structured event."""
    return round((monotonic() - started_at) * 1000, 3)


def _redact(value: object, *, parent_key: str | None = None) -> object:
    if parent_key is not None and _is_sensitive_key(parent_key):
        return "[redacted]"
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _redact(item, parent_key=str(key)) for key, item in mapping.items()}
    if isinstance(value, list):
        return [_redact(item, parent_key=parent_key) for item in cast(list[object], value)]
    if isinstance(value, tuple):
        return [_redact(item, parent_key=parent_key) for item in cast(tuple[object, ...], value)]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.replace("-", "_").lower()
    return normalized in _SENSITIVE_KEYS or normalized.endswith(
        ("_key", "_password", "_secret", "_token")
    )
