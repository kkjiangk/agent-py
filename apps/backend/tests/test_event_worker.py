from __future__ import annotations

import asyncio
from typing import cast

import pytest
from confluent_kafka import Message

from super_ai.events.broker import ConsumedMessage
from super_ai.events.worker import consume_events


class ProbeConsumer:
    def __init__(self, *, commit_failures: int = 0) -> None:
        self.poll_count = 0
        self.commits: list[int] = []
        self.commit_failures = commit_failures

    async def poll(self, timeout_seconds: float = 1.0) -> ConsumedMessage | None:
        del timeout_seconds
        offset = self.poll_count
        self.poll_count += 1
        if offset > 1:
            raise StopAsyncIteration
        return ConsumedMessage(
            topic="alerts", partition=0, offset=offset, key="incident",
            value=str(offset).encode(), native_message=cast(Message, object()),
        )

    async def commit(self, message: ConsumedMessage) -> None:
        if self.commit_failures:
            self.commit_failures -= 1
            raise RuntimeError("Injected commit failure")
        self.commits.append(message.offset)

    async def close(self) -> None:
        return None


class ProbeProcessor:
    def __init__(self, *, failures: int = 0) -> None:
        self.failures = failures
        self.attempts: list[bytes] = []

    async def process(self, raw_value: bytes) -> str:
        self.attempts.append(raw_value)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("Injected scheduling failure")
        return "scheduled"


@pytest.mark.asyncio
async def test_transient_failure_retries_record_before_polling_later_offset() -> None:
    consumer = ProbeConsumer()
    processor = ProbeProcessor(failures=1)
    with pytest.raises(StopAsyncIteration):
        await consume_events(consumer, processor, retry_base_seconds=0)
    assert processor.attempts == [b"0", b"0", b"1"]
    assert consumer.commits == [0, 1]


@pytest.mark.asyncio
async def test_exhausted_retry_exits_without_covering_failed_record() -> None:
    consumer = ProbeConsumer()
    processor = ProbeProcessor(failures=10)
    with pytest.raises(RuntimeError, match="scheduling"):
        await consume_events(consumer, processor, retry_base_seconds=0)
    assert consumer.poll_count == 1
    assert processor.attempts == [b"0", b"0", b"0"]
    assert consumer.commits == []


@pytest.mark.asyncio
async def test_commit_failure_replays_idempotent_processor_before_next_poll() -> None:
    consumer = ProbeConsumer(commit_failures=1)
    processor = ProbeProcessor()
    with pytest.raises(StopAsyncIteration):
        await consume_events(consumer, processor, retry_base_seconds=0)
    assert processor.attempts == [b"0", b"0", b"1"]
    assert consumer.commits == [0, 1]


@pytest.mark.asyncio
async def test_cancellation_during_backoff_preserves_offset() -> None:
    consumer = ProbeConsumer()
    processor = ProbeProcessor(failures=10)
    task = asyncio.create_task(consume_events(consumer, processor))
    while not processor.attempts:
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert consumer.commits == []
    assert consumer.poll_count == 1
