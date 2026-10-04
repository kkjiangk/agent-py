from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config

from super_ai.api.app import create_app


@pytest.mark.asyncio
async def test_chat_session_lifecycle_persists_history_and_generates_title(
    migrated_database_url: str,
) -> None:
    transport = httpx.ASGITransport(app=create_app(database_url=migrated_database_url))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user = await _register(client, "chat-owner@example.com", "Chat Owner")
        headers = _auth_headers(user["accessToken"])

        create_response = await client.post("/chat/sessions", headers=headers, json={})
        session_id = create_response.json()["data"]["id"]
        user_message_response = await client.post(
            f"/chat/sessions/{session_id}/messages",
            headers=headers,
            json={
                "role": "user",
                "content": "How do I restart the API service during an incident?",
                "metadata": {
                    "custom": {"source": "manual"},
                    "toolCallIds": ["tool_call_1"],
                },
            },
        )
        assistant_message_response = await client.post(
            f"/chat/sessions/{session_id}/messages",
            headers=headers,
            json={
                "role": "assistant",
                "content": "Use the restart runbook.",
                "metadata": {
                    "citations": [
                        {
                            "id": "chunk_1",
                            "title": "runbook.md",
                            "sourceType": "knowledge-base",
                            "chunkId": "chunk_1",
                            "documentId": "doc_1",
                            "knowledgeBaseId": f"kb_{user['user']['id']}",
                            "source": "runbook.md",
                            "metadata": {"section": "restart"},
                            "score": 0.91,
                        }
                    ]
                },
            },
        )
        detail_response = await client.get(f"/chat/sessions/{session_id}", headers=headers)
        list_response = await client.get("/chat/sessions", headers=headers)
        clear_response = await client.post(
            f"/chat/sessions/{session_id}/messages:clear",
            headers=headers,
        )
        cleared_detail_response = await client.get(f"/chat/sessions/{session_id}", headers=headers)
        delete_response = await client.delete(f"/chat/sessions/{session_id}", headers=headers)
        after_delete_list_response = await client.get("/chat/sessions", headers=headers)

    assert create_response.status_code == 201
    assert create_response.json()["data"]["title"] == "New chat"
    assert user_message_response.status_code == 201
    assert user_message_response.json()["data"]["session"]["title"] == (
        "How do I restart the API service during an incident?"
    )
    assert user_message_response.json()["data"]["message"]["metadata"]["toolCallIds"] == [
        "tool_call_1"
    ]
    assert assistant_message_response.status_code == 201
    assert (
        assistant_message_response.json()["data"]["message"]["metadata"]["citations"][0][
            "chunkId"
        ]
        == "chunk_1"
    )

    detail_payload = detail_response.json()["data"]
    assert detail_response.status_code == 200
    assert detail_payload["session"]["id"] == session_id
    assert [message["role"] for message in detail_payload["messages"]] == ["user", "assistant"]
    assert list_response.status_code == 200
    assert list_response.json()["data"]["items"][0]["id"] == session_id
    assert clear_response.status_code == 200
    assert clear_response.json()["data"] == {
        "sessionId": session_id,
        "cleared": True,
        "deletedMessages": 2,
    }
    assert cleared_detail_response.json()["data"]["messages"] == []
    assert delete_response.status_code == 200
    assert delete_response.json()["data"] == {"sessionId": session_id, "deleted": True}
    assert after_delete_list_response.json()["data"]["items"] == []


@pytest.mark.asyncio
async def test_chat_sessions_are_ordered_by_recent_updates(migrated_database_url: str) -> None:
    transport = httpx.ASGITransport(app=create_app(database_url=migrated_database_url))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user = await _register(client, "ordered@example.com", "Ordered User")
        headers = _auth_headers(user["accessToken"])

        first = (
            await client.post("/chat/sessions", headers=headers, json={"title": "First"})
        ).json()["data"]
        second = (
            await client.post("/chat/sessions", headers=headers, json={"title": "Second"})
        ).json()["data"]
        await client.post(
            f"/chat/sessions/{first['id']}/messages",
            headers=headers,
            json={"role": "user", "content": "touch first"},
        )

        list_response = await client.get("/chat/sessions", headers=headers)

    assert list_response.status_code == 200
    assert [item["id"] for item in list_response.json()["data"]["items"]][:2] == [
        first["id"],
        second["id"],
    ]


@pytest.mark.asyncio
async def test_chat_session_access_is_scoped_to_current_user(
    migrated_database_url: str,
) -> None:
    transport = httpx.ASGITransport(app=create_app(database_url=migrated_database_url))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user_a = await _register(client, "chat-a@example.com", "Chat A")
        user_b = await _register(client, "chat-b@example.com", "Chat B")
        session = (
            await client.post(
                "/chat/sessions",
                headers=_auth_headers(user_a["accessToken"]),
                json={"title": "Private"},
            )
        ).json()["data"]

        anonymous_list = await client.get("/chat/sessions")
        user_b_read = await client.get(
            f"/chat/sessions/{session['id']}",
            headers=_auth_headers(user_b["accessToken"]),
        )
        user_b_append = await client.post(
            f"/chat/sessions/{session['id']}/messages",
            headers=_auth_headers(user_b["accessToken"]),
            json={"role": "user", "content": "cross tenant"},
        )
        user_b_clear = await client.post(
            f"/chat/sessions/{session['id']}/messages:clear",
            headers=_auth_headers(user_b["accessToken"]),
        )
        user_b_delete = await client.delete(
            f"/chat/sessions/{session['id']}",
            headers=_auth_headers(user_b["accessToken"]),
        )
        owner_detail = await client.get(
            f"/chat/sessions/{session['id']}",
            headers=_auth_headers(user_a["accessToken"]),
        )

    assert anonymous_list.status_code == 401
    assert anonymous_list.json()["error"]["code"] == "AUTH_UNAUTHENTICATED"
    for response in [user_b_read, user_b_append, user_b_clear, user_b_delete]:
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "AUTH_FORBIDDEN"
    assert owner_detail.status_code == 200
    assert owner_detail.json()["data"]["session"]["id"] == session["id"]


async def _register(client: httpx.AsyncClient, email: str, display_name: str) -> dict[str, Any]:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "displayName": display_name,
            "password": "correct horse battery staple",
        },
    )
    return response.json()["data"]


def _auth_headers(token: object) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "chat-sessions-api.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"
