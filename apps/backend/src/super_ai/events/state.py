"""Redis-backed idempotency state for at-least-once event delivery."""
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import asyncio
from hashlib import sha256
from typing import Literal, Protocol, cast
from uuid import uuid4

from redis.asyncio import Redis

EventLeaseResult = Literal["acquired", "completed", "busy"]


class EventStateStore(Protocol):
    async def acquire(self, *, owner_user_id: str, event_id: str) -> EventLeaseResult:
        """Acquire a bounded processing lease unless the event completed."""
        ...

    async def mark_completed(self, *, owner_user_id: str, event_id: str) -> None:
        """Persist completed state and release the processing lease."""
        ...

    async def mark_failed(self, *, owner_user_id: str, event_id: str) -> None:
        """Release a failed lease so broker redelivery can retry."""
        ...

    async def close(self) -> None:
        """Release external resources."""
        ...


class RedisEventStateStore:
    """Atomic event leases and completion markers shared across workers."""

    _ACQUIRE_SCRIPT = """
local status_key = KEYS[1]
local lease_key = KEYS[2]
if redis.call('GET', status_key) == 'completed' then
  return 'completed'
end
if redis.call('SET', lease_key, ARGV[2], 'NX', 'EX', ARGV[1]) then
  return 'acquired'
end
return 'busy'
"""

    _COMPLETE_SCRIPT = """
if redis.call('GET', KEYS[2]) ~= ARGV[1] then
  return 0
end
redis.call('SET', KEYS[1], 'completed', 'EX', ARGV[2])
redis.call('DEL', KEYS[2])
return 1
"""
    _RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""

    def __init__(
        self,
        redis_url: str,
        *,
        lease_seconds: int,
        retention_seconds: int,
    ) -> None:
        self._lease_owner = uuid4().hex
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._lease_seconds = lease_seconds
        self._retention_seconds = retention_seconds

    async def acquire(self, *, owner_user_id: str, event_id: str) -> EventLeaseResult:
        status_key, lease_key = event_state_keys(owner_user_id, event_id)
        result = await self._redis.eval(
            self._ACQUIRE_SCRIPT,
            2,
            status_key,
            lease_key,
            str(self._lease_seconds),
            self._lease_owner,
        )
        if result not in {"acquired", "completed", "busy"}:
            raise RuntimeError("Unexpected event lease result.")
        return cast(EventLeaseResult, result)

    async def mark_completed(self, *, owner_user_id: str, event_id: str) -> None:
        status_key, lease_key = event_state_keys(owner_user_id, event_id)
        result = await self._redis.eval(
            self._COMPLETE_SCRIPT,
            2,
            status_key,
            lease_key,
            self._lease_owner,
            str(self._retention_seconds),
        )
        if result != 1:
            raise RuntimeError("Event processing lease expired or changed owner.")

    async def mark_failed(self, *, owner_user_id: str, event_id: str) -> None:
        _, lease_key = event_state_keys(owner_user_id, event_id)
        await self._redis.eval(self._RELEASE_SCRIPT, 1, lease_key, self._lease_owner)

    async def close(self) -> None:
        await self._redis.aclose()


class InMemoryEventStateStore:
    """Concurrency-safe state store used by unit tests."""

    def __init__(self) -> None:
        self._processing: set[tuple[str, str]] = set()
        self._completed: set[tuple[str, str]] = set()
        self._lock = asyncio.Lock()

    async def acquire(self, *, owner_user_id: str, event_id: str) -> EventLeaseResult:
        key = (owner_user_id, event_id)
        async with self._lock:
            if key in self._completed:
                return "completed"
            if key in self._processing:
                return "busy"
            self._processing.add(key)
            return "acquired"

    async def mark_completed(self, *, owner_user_id: str, event_id: str) -> None:
        key = (owner_user_id, event_id)
        async with self._lock:
            self._processing.discard(key)
            self._completed.add(key)

    async def mark_failed(self, *, owner_user_id: str, event_id: str) -> None:
        async with self._lock:
            self._processing.discard((owner_user_id, event_id))

    async def close(self) -> None:
        return None


def event_state_keys(owner_user_id: str, event_id: str) -> tuple[str, str]:
    # Hash structured identity instead of replacing separators, which can collide.
    identity = f"{len(owner_user_id)}:{owner_user_id}{event_id}"
    digest = sha256(identity.encode()).hexdigest()
    # The shared hash tag also keeps both Lua keys in one Redis Cluster slot.
    prefix = f"agent-py:event:{{{digest}}}"
    return f"{prefix}:status", f"{prefix}:lease"
