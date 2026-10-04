"""SQLite-leased durable worker runtime for local background work."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TypeAlias
from uuid import uuid4

from super_ai.memory.repositories import (
    BackgroundJobRecord,
    BackgroundJobRepository,
    JsonDict,
)
from super_ai.observability import emit_event

logger = logging.getLogger(__name__)
JobHandler: TypeAlias = Callable[["BackgroundJobContext"], Awaitable[None]]


class JobCancelled(RuntimeError):
    """Cooperative cancellation requested at a safe handler boundary."""


@dataclass(frozen=True, slots=True)
class BackgroundJobContext:
    """Narrow handler context backed by the durable repository."""

    job: BackgroundJobRecord
    repository: BackgroundJobRepository

    async def append_event(self, payload: JsonDict) -> None:
        await self.repository.append_event(
            owner_user_id=self.job.owner_user_id,
            job_id=self.job.id,
            payload=payload,
        )

    async def raise_if_cancelled(self) -> None:
        current = await self.repository.get(
            owner_user_id=self.job.owner_user_id,
            job_id=self.job.id,
        )
        if current is None or current.cancel_requested_at is not None:
            raise JobCancelled("Background job cancellation was requested.")


class BackgroundJobRuntime:
    """Run registered handlers using renewable SQLite leases."""

    def __init__(
        self,
        repository: BackgroundJobRepository,
        *,
        concurrency: int = 2,
        lease_seconds: int = 30,
        poll_seconds: float = 0.2,
    ) -> None:
        self._repository = repository
        self._concurrency = max(1, concurrency)
        self._lease_seconds = max(6, lease_seconds)
        self._poll_seconds = max(0.05, poll_seconds)
        self._handlers: dict[str, JobHandler] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()
        self._runtime_id = f"runtime_{uuid4().hex}"

    def register(self, kind: str, handler: JobHandler) -> None:
        if kind in self._handlers:
            raise ValueError(f"Background job handler already registered: {kind}")
        self._handlers[kind] = handler

    async def start(self) -> None:
        if self._workers:
            return
        self._stopping.clear()
        self._workers = [
            asyncio.create_task(self._worker_loop(index), name=f"background-worker-{index}")
            for index in range(self._concurrency)
        ]

    async def stop(self) -> None:
        self._stopping.set()
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []

    async def _worker_loop(self, index: int) -> None:
        worker_id = f"{self._runtime_id}:{index}"
        while not self._stopping.is_set():
            now = _utc_now()
            job = await self._repository.claim_next(
                worker_id=worker_id,
                lease_expires_at=now + timedelta(seconds=self._lease_seconds),
                now=now,
            )
            if job is None:
                await asyncio.sleep(self._poll_seconds)
                continue
            await self._execute(job, worker_id)

    async def _execute(self, job: BackgroundJobRecord, worker_id: str) -> None:
        handler = self._handlers.get(job.kind)
        if handler is None:
            await self._repository.handle_failure(
                job_id=job.id,
                worker_id=worker_id,
                error_message=f"No handler is registered for job kind: {job.kind}",
                retry_at=_utc_now(),
            )
            return

        emit_event(logger, "background.job.started", jobId=job.id, kind=job.kind)
        context = BackgroundJobContext(job=job, repository=self._repository)
        heartbeat = asyncio.create_task(self._heartbeat(job.id, worker_id))
        try:
            await context.raise_if_cancelled()
            await asyncio.wait_for(handler(context), timeout=job.timeout_seconds)
            await context.raise_if_cancelled()
        except JobCancelled:
            await self._repository.mark_cancelled(job_id=job.id, worker_id=worker_id)
            emit_event(logger, "background.job.cancelled", jobId=job.id, kind=job.kind)
        except Exception as exc:
            retry_at = _utc_now() + timedelta(seconds=min(30, 2**job.attempt))
            updated = await self._repository.handle_failure(
                job_id=job.id,
                worker_id=worker_id,
                error_message=_safe_error(exc),
                retry_at=retry_at,
            )
            emit_event(
                logger,
                "background.job.failed",
                jobId=job.id,
                kind=job.kind,
                final=updated is not None and updated.status == "failed",
                errorCategory=exc.__class__.__name__,
            )
        else:
            await self._repository.mark_succeeded(job_id=job.id, worker_id=worker_id)
            emit_event(logger, "background.job.completed", jobId=job.id, kind=job.kind)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _heartbeat(self, job_id: str, worker_id: str) -> None:
        interval = self._lease_seconds / 3
        while not self._stopping.is_set():
            await asyncio.sleep(interval)
            renewed = await self._repository.renew_lease(
                job_id=job_id,
                worker_id=worker_id,
                lease_expires_at=_utc_now() + timedelta(seconds=self._lease_seconds),
            )
            if not renewed:
                return


def _safe_error(error: Exception) -> str:
    if isinstance(error, asyncio.TimeoutError):
        return "Background job timed out."
    text = str(error).strip()
    return (text or error.__class__.__name__)[:1000]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
