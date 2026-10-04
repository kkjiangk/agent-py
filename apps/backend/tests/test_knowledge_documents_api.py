from __future__ import annotations

import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from pypdf import PdfWriter

from super_ai.api.app import create_app
from super_ai.vector_store import MilvusHealthCheckResult


@pytest.mark.asyncio
async def test_document_upload_list_detail_delete_and_vector_cleanup(
    migrated_database_url: str,
) -> None:
    vector_store = FakeVectorStore()
    transport = httpx.ASGITransport(
        app=create_app(database_url=migrated_database_url, vector_store=vector_store)
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user_a = await _register(client, "a@example.com", "User A")
        user_b = await _register(client, "b@example.com", "User B")
        kb_a = f"kb_{user_a['user']['id']}"
        content = b"# Runbook\nRestart API"

        upload_response = await client.post(
            f"/knowledge-bases/{kb_a}/documents",
            headers=_auth_headers(user_a["accessToken"]),
            files={"file": ("runbook.md", content, "text/markdown")},
        )
        upload_payload = upload_response.json()
        document = upload_payload["data"]["document"]

        assert upload_response.status_code == 201
        assert document["ownerUserId"] == user_a["user"]["id"]
        assert document["knowledgeBaseId"] == kb_a
        assert document["filename"] == "runbook.md"
        assert document["sizeBytes"] == len(content)
        assert document["mimeType"] == "text/markdown"
        assert document["contentHash"] == f"sha256:{sha256(content).hexdigest()}"
        assert document["status"] == "ready"
        assert document["indexStatus"] == "pending"

        list_response = await client.get(
            f"/knowledge-bases/{kb_a}/documents",
            headers=_auth_headers(user_a["accessToken"]),
        )
        detail_response = await client.get(
            f"/knowledge-bases/{kb_a}/documents/{document['id']}",
            headers=_auth_headers(user_a["accessToken"]),
        )
        cross_tenant_detail = await client.get(
            f"/knowledge-bases/{kb_a}/documents/{document['id']}",
            headers=_auth_headers(user_b["accessToken"]),
        )
        delete_response = await client.delete(
            f"/knowledge-bases/{kb_a}/documents/{document['id']}",
            headers=_auth_headers(user_a["accessToken"]),
        )
        after_delete = await client.get(
            f"/knowledge-bases/{kb_a}/documents",
            headers=_auth_headers(user_a["accessToken"]),
        )

        assert list_response.status_code == 200
        assert [item["id"] for item in list_response.json()["data"]["items"]] == [document["id"]]
        assert detail_response.status_code == 200
        assert detail_response.json()["data"]["id"] == document["id"]
        assert cross_tenant_detail.status_code == 403
        assert cross_tenant_detail.json()["error"]["code"] == "AUTH_FORBIDDEN"
        assert delete_response.status_code == 200
        assert delete_response.json()["data"] == {"deleted": True, "documentId": document["id"]}
        assert after_delete.json()["data"]["items"] == []
        assert vector_store.deleted_documents == [
            {
                "tenant_id": user_a["user"]["id"],
                "knowledge_base_id": kb_a,
                "document_id": document["id"],
            }
        ]


@pytest.mark.asyncio
async def test_document_upload_rejects_duplicate_without_overwrite_and_replaces_with_overwrite(
    migrated_database_url: str,
) -> None:
    vector_store = FakeVectorStore()
    transport = httpx.ASGITransport(
        app=create_app(database_url=migrated_database_url, vector_store=vector_store)
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user = await _register(client, "dup@example.com", "Duplicate")
        kb_id = f"kb_{user['user']['id']}"
        headers = _auth_headers(user["accessToken"])

        first = await client.post(
            f"/knowledge-bases/{kb_id}/documents",
            headers=headers,
            files={"file": ("runbook.md", b"same", "text/markdown")},
        )
        duplicate = await client.post(
            f"/knowledge-bases/{kb_id}/documents",
            headers=headers,
            files={"file": ("copy.md", b"same", "text/markdown")},
        )
        overwrite = await client.post(
            f"/knowledge-bases/{kb_id}/documents",
            headers=headers,
            data={"overwrite": "true"},
            files={"file": ("copy.md", b"same", "text/markdown")},
        )

        assert first.status_code == 201
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "BUSINESS_CONFLICT"
        assert overwrite.status_code == 201
        assert overwrite.json()["data"]["overwrite"] is True
        assert (
            overwrite.json()["data"]["duplicateOfDocumentId"]
            == first.json()["data"]["document"]["id"]
        )
        assert vector_store.deleted_documents == [
            {
                "tenant_id": user["user"]["id"],
                "knowledge_base_id": kb_id,
                "document_id": first.json()["data"]["document"]["id"],
            }
        ]


@pytest.mark.asyncio
async def test_document_upload_persists_chunking_configuration_and_returns_preview(
    migrated_database_url: str,
) -> None:
    transport = httpx.ASGITransport(app=create_app(database_url=migrated_database_url))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user = await _register(client, "chunking@example.com", "Chunking")
        headers = _auth_headers(user["accessToken"])
        kb_id = f"kb_{user['user']['id']}"
        configuration = {
            "strategy": "markdown-heading",
        }
        upload = await client.post(
            f"/knowledge-bases/{kb_id}/documents",
            headers=headers,
            data={"chunking": json.dumps(configuration)},
            files={
                "file": (
                    "runbook.md",
                    b"# Restart\nRestart the API.\n\n## Verify\nCheck readiness.",
                    "text/markdown",
                )
            },
        )
        document = upload.json()["data"]["document"]
        preview = await client.get(
            f"/knowledge-bases/{kb_id}/documents/{document['id']}/chunk-preview",
            headers=headers,
        )
        invalid = await client.post(
            f"/knowledge-bases/{kb_id}/documents",
            headers=headers,
            data={"chunking": json.dumps({"strategy": "unknown", "maxCharacters": 100})},
            files={"file": ("invalid.md", b"text", "text/markdown")},
        )
        invalid_fixed = await client.post(
            f"/knowledge-bases/{kb_id}/documents",
            headers=headers,
            data={"chunking": json.dumps({"strategy": "fixed-character"})},
            files={"file": ("invalid-fixed.md", b"text", "text/markdown")},
        )

    assert upload.status_code == 201
    assert document["chunking"] == configuration
    assert preview.status_code == 200
    assert preview.json()["data"]["preview"]["configuration"] == configuration
    assert preview.json()["data"]["preview"]["items"][0]["headingPath"] == "Restart"
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "VALIDATION_INVALID_ARGUMENT"
    assert invalid_fixed.status_code == 400
    assert invalid_fixed.json()["error"]["code"] == "VALIDATION_INVALID_ARGUMENT"


@pytest.mark.asyncio
async def test_document_upload_rejects_unsupported_and_oversized_files(
    migrated_database_url: str,
) -> None:
    transport = httpx.ASGITransport(app=create_app(database_url=migrated_database_url))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user = await _register(client, "policy@example.com", "Policy")
        kb_id = f"kb_{user['user']['id']}"
        headers = _auth_headers(user["accessToken"])

        unsupported = await client.post(
            f"/knowledge-bases/{kb_id}/documents",
            headers=headers,
            files={"file": ("script.exe", b"bad", "application/octet-stream")},
        )
        markdown_octet_stream = await client.post(
            f"/knowledge-bases/{kb_id}/documents",
            headers=headers,
            files={"file": ("runbook.md", b"# Runbook", "application/octet-stream")},
        )
        unsupported_text = await client.post(
            f"/knowledge-bases/{kb_id}/documents",
            headers=headers,
            files={"file": ("notes.txt", b"plain", "text/plain")},
        )
        oversized = await client.post(
            f"/knowledge-bases/{kb_id}/documents",
            headers=headers,
            files={"file": ("large.md", b"x" * (10 * 1024 * 1024 + 1), "text/markdown")},
        )
        pdf_without_text = await client.post(
            f"/knowledge-bases/{kb_id}/documents",
            headers=headers,
            files={"file": ("scan.pdf", _blank_pdf_bytes(), "application/pdf")},
        )

        assert unsupported.status_code == 400
        assert unsupported.json()["error"]["code"] == "VALIDATION_INVALID_ARGUMENT"
        assert unsupported.json()["error"]["message"] == "仅支持 Markdown(.md) 与 PDF(.pdf) 文件。"
        assert markdown_octet_stream.status_code == 201
        assert unsupported_text.status_code == 400
        assert unsupported_text.json()["error"]["code"] == "VALIDATION_INVALID_ARGUMENT"
        assert oversized.status_code == 400
        assert oversized.json()["error"]["code"] == "VALIDATION_INVALID_ARGUMENT"
        assert pdf_without_text.status_code == 400
        assert pdf_without_text.json()["error"]["message"] == (
            "该 PDF 没有可索引文本，请上传包含可选择文本的 PDF 或转换为 Markdown。"
        )


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


class FakeVectorStore:
    def __init__(self) -> None:
        self.deleted_documents: list[dict[str, str]] = []

    def health_check(self) -> MilvusHealthCheckResult:
        return MilvusHealthCheckResult(
            ok=True,
            uri="http://milvus:19530",
            collection_name="knowledge_chunks",
            latency_ms=1.0,
        )

    def delete_document_chunks(
        self,
        *,
        tenant_id: str,
        knowledge_base_id: str,
        document_id: str,
    ) -> None:
        self.deleted_documents.append(
            {
                "tenant_id": tenant_id,
                "knowledge_base_id": knowledge_base_id,
                "document_id": document_id,
            }
        )


def _blank_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "documents-api.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"
