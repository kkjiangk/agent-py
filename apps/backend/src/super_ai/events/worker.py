"""Standalone Kafka-to-durable-AIOps worker entry point."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Protocol, cast

from super_ai.api.app import create_app
from super_ai.events.broker import EventConsumer, KafkaEventConsumer, KafkaEventPublisher
from super_ai.events.config import load_event_ingestion_settings
from super_ai.events.service import AlertEventProcessor
from super_ai.events.state import RedisEventStateStore
from super_ai.jobs import BackgroundJobRuntime
from super_ai.memory.repositories import MemoryRepositories
from super_ai.observability import configure_structured_logging, emit_event

logger = logging.getLogger(__name__)


class EventProcessor(Protocol):
    async def process(self, raw_value: bytes) -> str: ...


async def consume_events(
    consumer: EventConsumer,
    processor: EventProcessor,
    *,
    max_attempts: int = 3,
    retry_base_seconds: float = 1.0,
) -> None:
    """Retry one record, including its commit, before polling a later record.

    Exhaustion exits the process with the offset uncommitted. A restarted worker
    can replay it; a later successful commit must never cover a failed record.
    Backoff is bounded; broker operations retain their own transport timeouts.
    """
    if not 1 <= max_attempts <= 5 or not 0 <= retry_base_seconds <= 5:
        raise ValueError("Invalid bounded event retry policy.")
    while True:
        message = await consumer.poll()
        if message is None:
            continue
        for attempt in range(1, max_attempts + 1):
            try:
                disposition = await processor.process(message.value)
                await consumer.commit(message)
            except Exception as exc:
                emit_event(
                    logger,
                    "event.consume.failed",
                    topic=message.topic,
                    partition=message.partition,
                    offset=message.offset,
                    attempt=attempt,
                    errorCategory=exc.__class__.__name__,
                )
                if attempt == max_attempts:
                    raise
                await asyncio.sleep(min(5.0, retry_base_seconds * 2 ** (attempt - 1)))
            else:
                emit_event(
                    logger,
                    "event.consume.completed",
                    topic=message.topic,
                    partition=message.partition,
                    offset=message.offset,
                    disposition=disposition,
                )
                break


async def run_worker(*, project_config_path: Path | str | None = None) -> None:
    """Consume alerts forever and commit only after durable scheduling or DLQ."""
    configure_structured_logging()
    settings = load_event_ingestion_settings(config_path=project_config_path)
    app = create_app(project_config_path=project_config_path)
    publisher = KafkaEventPublisher(settings)
    consumer = KafkaEventConsumer(settings)
    state_store = RedisEventStateStore(
        settings.redis_url,
        lease_seconds=settings.event_lease_seconds,
        retention_seconds=settings.event_retention_seconds,
    )
    async with app.router.lifespan_context(app):
        processor = AlertEventProcessor(
            repositories=cast(MemoryRepositories, app.state.memory_repositories),
            runtime=cast(BackgroundJobRuntime, app.state.background_job_runtime),
            publisher=publisher,
            state_store=state_store,
            settings=settings,
        )
        try:
            await consume_events(consumer, processor)
        finally:
            await consumer.close()
            await publisher.close()
            await state_store.close()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
