"""Authentication router and reusable authenticated-user dependency."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from super_ai.auth.repositories import UserRecord
from super_ai.auth.service import AuthError, AuthResult, AuthService

from .responses import ApiErrorException, success_response
from .schemas import LoginRequest, RegisterRequest

bearer_scheme = HTTPBearer(auto_error=False)
BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]
auth_router = APIRouter()


async def current_user(
    request: Request,
    credentials: BearerCredentials,
) -> UserRecord:
    token = _bearer_token(credentials)
    try:
        return await auth_service(request).authenticate_token(token)
    except AuthError as exc:
        raise _api_error(exc) from exc


def auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


def _bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiErrorException("AUTH_UNAUTHENTICATED")
    return credentials.credentials


def _api_error(exc: AuthError) -> ApiErrorException:
    return ApiErrorException(exc.code, str(exc))


def user_payload(user: UserRecord) -> dict[str, str]:
    return {
        "id": user.id,
        "email": user.email,
        "displayName": user.display_name,
        "createdAt": user.created_at.isoformat(),
    }


def _auth_result_payload(result: AuthResult) -> dict[str, object]:
    return {
        "user": user_payload(result.user),
        "accessToken": result.access_token,
        "tokenType": result.token_type,
    }


@auth_router.post("/auth/register")
async def register(request: Request, body: RegisterRequest) -> object:
    service = auth_service(request)
    try:
        result = await service.register(
            email=body.email,
            display_name=body.display_name,
            password=body.password,
        )
    except AuthError as exc:
        raise _api_error(exc) from exc
    return success_response(request, _auth_result_payload(result), status_code=201)


@auth_router.post("/auth/login")
async def login(request: Request, body: LoginRequest) -> object:
    service = auth_service(request)
    try:
        result = await service.login(email=body.email, password=body.password)
    except AuthError as exc:
        raise _api_error(exc) from exc
    return success_response(request, _auth_result_payload(result))


@auth_router.post("/auth/logout")
async def logout(
    request: Request,
    credentials: BearerCredentials,
) -> object:
    token = _bearer_token(credentials)
    try:
        await auth_service(request).logout(token)
    except AuthError as exc:
        raise _api_error(exc) from exc
    return success_response(request, {"revoked": True})


@auth_router.get("/auth/me")
async def get_current_user(
    request: Request,
    user: Annotated[UserRecord, Depends(current_user)],
) -> object:
    return success_response(request, user_payload(user))
