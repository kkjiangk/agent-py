from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config

from super_ai.api.app import create_app


@pytest.mark.asyncio
async def test_register_login_me_logout_and_revoked_token_flow(
    migrated_database_url: str,
) -> None:
    transport = httpx.ASGITransport(app=create_app(database_url=migrated_database_url))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        register_response = await client.post(
            "/auth/register",
            json={
                "email": "timi@example.com",
                "displayName": "Timi",
                "password": "correct horse battery staple",
            },
        )
        register_payload = register_response.json()
        token = register_payload["data"]["accessToken"]

        assert register_response.status_code == 201
        assert register_payload["ok"] is True
        assert register_payload["data"]["user"]["email"] == "timi@example.com"
        assert "password" not in str(register_payload).lower()

        me_response = await client.get("/auth/me", headers=_auth_headers(token))
        assert me_response.status_code == 200
        assert me_response.json()["data"]["email"] == "timi@example.com"

        logout_response = await client.post("/auth/logout", headers=_auth_headers(token))
        assert logout_response.status_code == 200

        revoked_response = await client.get("/auth/me", headers=_auth_headers(token))
        assert revoked_response.status_code == 401
        assert revoked_response.json()["error"]["code"] == "AUTH_SESSION_REVOKED"

        login_response = await client.post(
            "/auth/login",
            json={"email": "timi@example.com", "password": "correct horse battery staple"},
        )
        assert login_response.status_code == 200
        assert login_response.json()["data"]["accessToken"] != token


@pytest.mark.asyncio
async def test_auth_errors_use_unified_response_shape(migrated_database_url: str) -> None:
    transport = httpx.ASGITransport(app=create_app(database_url=migrated_database_url))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        invalid_login = await client.post(
            "/auth/login",
            json={"email": "missing@example.com", "password": "wrong password"},
        )
        anonymous_me = await client.get("/auth/me")

        assert invalid_login.status_code == 401
        assert invalid_login.json()["ok"] is False
        assert invalid_login.json()["error"]["code"] == "AUTH_INVALID_CREDENTIALS"
        assert invalid_login.json()["meta"]["requestId"]
        assert anonymous_me.status_code == 401
        assert anonymous_me.json()["error"]["code"] == "AUTH_UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_local_frontend_cors_preflight_is_allowed(migrated_database_url: str) -> None:
    transport = httpx.ASGITransport(app=create_app(database_url=migrated_database_url))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.options(
            "/auth/register",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


@pytest.mark.asyncio
async def test_protected_resources_require_authentication(migrated_database_url: str) -> None:
    transport = httpx.ASGITransport(app=create_app(database_url=migrated_database_url))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        protected_requests = [
            await client.get("/knowledge-bases"),
            await client.post("/chat/sessions", json={"title": "incident"}),
            await client.post("/aiops/diagnostics", json={"query": "latency"}),
        ]
        assert all(response.status_code == 401 for response in protected_requests)
        assert all(
            response.json()["error"]["code"] == "AUTH_UNAUTHENTICATED"
            for response in protected_requests
        )

        token = (
            await client.post(
                "/auth/register",
                json={
                    "email": "timi@example.com",
                    "displayName": "Timi",
                    "password": "correct horse battery staple",
                },
            )
        ).json()["data"]["accessToken"]

        knowledge_base_response = await client.get("/knowledge-bases", headers=_auth_headers(token))
        assert knowledge_base_response.status_code == 200
        assert (
            await client.post(
                "/chat/sessions",
                json={"title": "incident"},
                headers=_auth_headers(token),
            )
        ).status_code == 201
        assert (
            await client.post(
                "/aiops/diagnostics",
                json={"query": "latency"},
                headers=_auth_headers(token),
            )
        ).status_code == 202


@pytest.mark.asyncio
async def test_protected_resources_are_scoped_to_current_user(
    migrated_database_url: str,
) -> None:
    transport = httpx.ASGITransport(app=create_app(database_url=migrated_database_url))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user_a = (
            await client.post(
                "/auth/register",
                json={
                    "email": "a@example.com",
                    "displayName": "User A",
                    "password": "correct horse battery staple",
                },
            )
        ).json()["data"]
        user_b = (
            await client.post(
                "/auth/register",
                json={
                    "email": "b@example.com",
                    "displayName": "User B",
                    "password": "correct horse battery staple",
                },
            )
        ).json()["data"]

        chat_response = await client.post(
            "/chat/sessions",
            json={"title": "User A incident"},
            headers=_auth_headers(user_a["accessToken"]),
        )
        diagnostic_response = await client.post(
            "/aiops/diagnostics",
            json={"query": "latency for user A"},
            headers=_auth_headers(user_a["accessToken"]),
        )
        kb_response = await client.get(
            "/knowledge-bases",
            headers=_auth_headers(user_b["accessToken"]),
        )

        assert chat_response.status_code == 201
        assert chat_response.json()["data"]["ownerUserId"] == user_a["user"]["id"]
        assert diagnostic_response.status_code == 202
        assert diagnostic_response.json()["data"]["ownerUserId"] == user_a["user"]["id"]
        assert kb_response.status_code == 200
        knowledge_base_items = kb_response.json()["data"]["items"]
        assert all(
            item["ownerUserId"] == user_b["user"]["id"] for item in knowledge_base_items
        )

        user_b_chat_read = await client.get(
            f"/chat/sessions/{chat_response.json()['data']['id']}",
            headers=_auth_headers(user_b["accessToken"]),
        )
        user_b_diagnostic_read = await client.get(
            f"/aiops/diagnostics/{diagnostic_response.json()['data']['id']}",
            headers=_auth_headers(user_b["accessToken"]),
        )

        assert user_b_chat_read.status_code == 403
        assert user_b_chat_read.json()["error"]["code"] == "AUTH_FORBIDDEN"
        assert user_b_diagnostic_read.status_code == 403
        assert user_b_diagnostic_read.json()["error"]["code"] == "AUTH_FORBIDDEN"


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "auth-api.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"
