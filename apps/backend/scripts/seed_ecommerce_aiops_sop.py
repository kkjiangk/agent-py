"""Upload and index the explicit e-commerce quant incident SOP through the local API."""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import cast

import httpx

from super_ai.aiops.fixtures import build_java_ecommerce_sop_documents
from super_ai.project_config import project_config_section, required_int, required_str

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SOP_PATH = REPOSITORY_ROOT / "docs" / "aiops" / "ecommerce-quant-pricing-latency-sop.md"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--profile",
        choices=("java-ecommerce", "quant"),
        default="java-ecommerce",
    )
    args = parser.parse_args()
    config = project_config_section("aiopsDemo")
    base_url = required_str(config, "backendBaseUrl").rstrip("/")
    email = required_str(config, "email")
    password = required_str(config, "password")
    display_name = required_str(config, "displayName")
    poll_interval = required_int(config, "pollIntervalSeconds")
    documents = (
        [
            (document.filename, document.content.encode("utf-8"))
            for document in build_java_ecommerce_sop_documents()
        ]
        if args.profile == "java-ecommerce"
        else [(SOP_PATH.name, SOP_PATH.read_bytes())]
    )
    indexed_document_ids: list[str] = []
    with httpx.Client(base_url=base_url, timeout=15) as client:
        auth = _register_or_login(client, email=email, password=password, display_name=display_name)
        user = _object(auth["user"])
        token = _string(auth["accessToken"])
        user_id = _string(user["id"])
        headers = {"Authorization": f"Bearer {token}"}
        knowledge_base_id = f"kb_{user_id}"
        for filename, content in documents:
            upload = client.post(
                f"/knowledge-bases/{knowledge_base_id}/documents",
                headers=headers,
                data={"overwrite": "true"},
                files={"file": (filename, content, "text/markdown")},
            )
            upload.raise_for_status()
            document = _object(_object(upload.json())["data"])["document"]
            document_id = _string(_object(document)["id"])
            task_response = client.post(
                f"/knowledge-bases/{knowledge_base_id}/documents/{document_id}/index-tasks",
                headers=headers,
            )
            task_response.raise_for_status()
            task = _object(_object(task_response.json())["data"])["task"]
            task_id = _string(_object(task)["id"])
            _wait_for_index(
                client,
                headers=headers,
                knowledge_base_id=knowledge_base_id,
                document_id=document_id,
                task_id=task_id,
                poll_interval_seconds=poll_interval,
                deadline=time.monotonic() + required_int(config, "indexWaitSeconds"),
            )
            indexed_document_ids.append(document_id)
    print(f"Indexed {len(indexed_document_ids)} {args.profile} SOP documents for {email}.")


def _register_or_login(
    client: httpx.Client,
    *,
    email: str,
    password: str,
    display_name: str,
) -> dict[str, object]:
    registration = client.post(
        "/auth/register",
        json={"email": email, "password": password, "displayName": display_name},
    )
    response = registration
    if registration.status_code == 409:
        response = client.post("/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    return _object(_object(response.json())["data"])


def _wait_for_index(
    client: httpx.Client,
    *,
    headers: dict[str, str],
    knowledge_base_id: str,
    document_id: str,
    task_id: str,
    poll_interval_seconds: int,
    deadline: float,
) -> None:
    endpoint = (
        f"/knowledge-bases/{knowledge_base_id}/documents/{document_id}/index-tasks/{task_id}"
    )
    while time.monotonic() < deadline:
        response = client.get(endpoint, headers=headers)
        response.raise_for_status()
        task = _object(_object(response.json())["data"])
        status = _string(task["status"])
        if status == "succeeded":
            return
        if status == "failed":
            raise SystemExit("SOP indexing failed; inspect the local backend logs.")
        time.sleep(poll_interval_seconds)
    raise SystemExit("Timed out while waiting for SOP indexing.")


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SystemExit("The local backend returned an invalid response.")
    return cast(dict[str, object], value)


def _string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise SystemExit("The local backend returned an invalid response.")
    return value


if __name__ == "__main__":
    main()
