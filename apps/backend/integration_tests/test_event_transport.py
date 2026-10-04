"""Opt-in real local Kafka/Redis checks; fail clearly when dependencies are absent."""
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from confluent_kafka.admin import AdminClient
from confluent_kafka.cimpl import NewTopic
from redis.asyncio import Redis

from super_ai.events.broker import KafkaEventConsumer, KafkaEventPublisher
from super_ai.events.config import EventIngestionSettings, load_event_ingestion_settings
from super_ai.events.models import BrokerAlertEnvelope
from super_ai.events.service import AlertEventProcessor
from super_ai.events.state import RedisEventStateStore, event_state_keys
from super_ai.events.worker import consume_events
from super_ai.jobs import BackgroundJobRuntime
from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.sqlite import create_sqlite_memory_repositories


@pytest.fixture
async def settings() -> AsyncIterator[EventIngestionSettings]:
    unique = f"agent-py-integration-{uuid4().hex}"
    template = Path(__file__).resolve().parents[3] / "config/project.template.json"
    settings = replace(
        load_event_ingestion_settings(config_path=template),
        client_id=unique,
        consumer_group=unique,
        alerts_topic=f"{unique}-alerts",
        updates_topic=f"{unique}-updates",
        dlq_topic=f"{unique}-dlq",
        remediation_topic=f"{unique}-commands",
    )
    admin = AdminClient({"bootstrap.servers": settings.bootstrap_servers})
    topics = [settings.alerts_topic, settings.updates_topic, settings.dlq_topic]
    futures = admin.create_topics([NewTopic(topic, 1, 1) for topic in topics])
    for future in futures.values():
        await asyncio.to_thread(future.result, 30)
    try:
        yield settings
    finally:
        # Only delete resources created by this fixture; never touch application topics.
        for future in admin.delete_topics(topics).values():
            await asyncio.to_thread(future.result, 30)
        for future in admin.delete_consumer_groups([unique]).values():
            try:
                await asyncio.to_thread(future.result, 30)
            except Exception:
                pass  # A test may never have created the group.


@pytest.mark.asyncio
async def test_real_redis_distinguishes_busy_completion_and_fences_expired_owner() -> None:
    owner, event = f"integration-{uuid4().hex}", "event-1"
    first = RedisEventStateStore("redis://127.0.0.1:6379/0", lease_seconds=1, retention_seconds=30)
    second = RedisEventStateStore(
        "redis://127.0.0.1:6379/0", lease_seconds=30, retention_seconds=30
    )
    redis = Redis.from_url("redis://127.0.0.1:6379/0", decode_responses=True)
    keys = event_state_keys(owner, event)
    try:
        assert await first.acquire(owner_user_id=owner, event_id=event) == "acquired"
        assert await second.acquire(owner_user_id=owner, event_id=event) == "busy"
        await redis.pexpire(keys[1], 1)
        await asyncio.sleep(0.02)
        assert await second.acquire(owner_user_id=owner, event_id=event) == "acquired"
        await first.mark_failed(owner_user_id=owner, event_id=event)
        assert await first.acquire(owner_user_id=owner, event_id=event) == "busy"
        with pytest.raises(RuntimeError, match="lease"):
            await first.mark_completed(owner_user_id=owner, event_id=event)
        await second.mark_completed(owner_user_id=owner, event_id=event)
        assert await first.acquire(owner_user_id=owner, event_id=event) == "completed"
    finally:
        await redis.delete(*keys)
        await redis.aclose()
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_failed_real_kafka_record_is_replayed_after_consumer_restart(
    settings: EventIngestionSettings,
) -> None:
    class FailingProcessor:
        async def process(self, raw_value: bytes) -> str:
            assert raw_value == b"first"
            raise RuntimeError("Injected processing failure")

    publisher = KafkaEventPublisher(settings)
    consumer = KafkaEventConsumer(settings)
    try:
        first = await publisher.publish(topic=settings.alerts_topic, key="incident", value=b"first")
        await publisher.publish(topic=settings.alerts_topic, key="incident", value=b"second")
        with pytest.raises(RuntimeError, match="Injected"):
            await asyncio.wait_for(consume_events(consumer, FailingProcessor(), max_attempts=1), 30)
    finally:
        await consumer.close()
        await publisher.close()
    replay = KafkaEventConsumer(settings)
    try:

        async def poll_value() -> bytes:
            while True:
                message = await replay.poll(0.5)
                if message is not None:
                    if message.value == b"first":
                        assert message.offset == first.offset
                    await replay.commit(message)
                    return message.value

        assert await asyncio.wait_for(poll_value(), 30) == b"first"
        assert await asyncio.wait_for(poll_value(), 10) == b"second"
    finally:
        await replay.close()


@pytest.mark.asyncio
async def test_real_redis_and_kafka_schedule_only_one_durable_job_on_redelivery(
    settings: EventIngestionSettings,
    tmp_path: Path,
) -> None:
    class SchedulingOnlyRuntime:
        async def start(self) -> None:
            return None

    url = f"sqlite+aiosqlite:///{tmp_path / 'integration.sqlite3'}"
    migration = Config("alembic.ini")
    migration.set_main_option("sqlalchemy.url", url)
    await asyncio.to_thread(command.upgrade, migration, "head")
    engine = create_memory_engine(url)
    repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
    publisher = KafkaEventPublisher(settings)
    store = RedisEventStateStore(settings.redis_url, lease_seconds=30, retention_seconds=30)
    owner = f"integration-{uuid4().hex}"
    envelope = BrokerAlertEnvelope(
        eventId="event",
        incidentId="incident",
        diagnosticId=f"diagnostic-{uuid4().hex}",
        ownerUserId=owner,
        service="test-only",
        severity="P1",
        alertType="timeout",
        occurredAt=datetime.now(timezone.utc),
        payload={},
    )
    try:
        processor = AlertEventProcessor(
            repositories=repositories,
            runtime=cast(BackgroundJobRuntime, SchedulingOnlyRuntime()),
            publisher=publisher,
            state_store=store,
            settings=settings,
        )
        assert (
            await processor.process(envelope.model_dump_json(by_alias=True).encode()) == "scheduled"
        )
        assert (
            await processor.process(envelope.model_dump_json(by_alias=True).encode()) == "duplicate"
        )
        assert repositories.background_jobs is not None
        assert len(await repositories.background_jobs.list(owner_user_id=owner)) == 1
        assert (
            await repositories.diagnostics.get_task(
                owner_user_id="other-owner", task_id=envelope.diagnostic_id
            )
            is None
        )
    finally:
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        await redis.delete(*event_state_keys(owner, envelope.event_id))
        await redis.aclose()
        await store.close()
        await publisher.close()
        await engine.dispose()
