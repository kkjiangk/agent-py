"""Unified API response helpers."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse

from super_ai.error_catalog import ERROR_DEFINITIONS


@dataclass(frozen=True, slots=True)
class ApiErrorException(Exception):
    code: str
    message: str | None = None


def success_response(request: Request, data: object, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": True,
            "data": data,
            "meta": {"requestId": _request_id(request)},
        },
    )


def error_response(request: Request, code: str, *, message: str | None = None) -> JSONResponse:
    category, http_status, default_message = ERROR_DEFINITIONS[code]
    return JSONResponse(
        status_code=http_status,
        content={
            "ok": False,
            "error": {
                "code": code,
                "category": category,
                "httpStatus": http_status,
                "message": message or default_message,
            },
            "meta": {"requestId": _request_id(request)},
        },
    )


def _request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str):
        return request_id
    return request.headers.get("x-request-id") or f"req_{uuid4().hex}"
