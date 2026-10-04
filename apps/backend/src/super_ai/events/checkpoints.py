"""Redis mirror for resumable AIOps workflow node state."""
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import json
from typing import Protocol

from redis.asyncio import Redis

from super_ai.memory.repositories import JsonDict


class WorkflowCheckpointStore(Protocol):
    async def save(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        node: str,
        payload: JsonDict,
    ) -> None:
        """Save the latest owner-scoped node checkpoint."""
        ...

    async def close(self) -> None:
        """Release external resources."""
        ...


class RedisWorkflowCheckpointStore:
    """Persist latest node checkpoints in Redis while SQLite retains the audit history."""

    def __init__(self, redis_url: str, *, retention_seconds: int) -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._retention_seconds = retention_seconds

    async def save(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        node: str,
        payload: JsonDict,
    ) -> None:
        safe_owner = owner_user_id.replace(":", "_")
        safe_task = task_id.replace(":", "_")
        safe_node = node.replace(":", "_")
        key = f"agent-py:workflow:{safe_owner}:{safe_task}:{safe_node}"
        value = json.dumps(
            {"taskId": task_id, "node": node, "payload": payload},
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        await self._redis.set(key, value, ex=self._retention_seconds)

    async def close(self) -> None:
        await self._redis.aclose()


class InMemoryWorkflowCheckpointStore:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str, JsonDict]] = []

    async def save(
        self,
        *,
        owner_user_id: str,
        task_id: str,
        node: str,
        payload: JsonDict,
    ) -> None:
        self.items.append((owner_user_id, task_id, node, payload))

    async def close(self) -> None:
        return None

