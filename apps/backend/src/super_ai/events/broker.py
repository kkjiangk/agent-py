"""Lazy Kafka adapters with idempotent production and manual offset control."""
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from confluent_kafka import Consumer, KafkaError, KafkaException, Message, Producer

from super_ai.events.config import EventIngestionSettings


class BrokerUnavailableError(RuntimeError):
    """Raised when a broker operation cannot complete safely."""


@dataclass(frozen=True, slots=True)
class PublishReceipt:
    topic: str
    partition: int
    offset: int


@dataclass(frozen=True, slots=True)
class ConsumedMessage:
    topic: str
    partition: int
    offset: int
    key: str
    value: bytes
    native_message: Message


class EventPublisher(Protocol):
    async def publish(self, *, topic: str, key: str, value: bytes) -> PublishReceipt:
        """Publish one keyed event after broker acknowledgement."""
        ...

    async def close(self) -> None:
        """Flush and release the publisher."""
        ...


class EventConsumer(Protocol):
    async def poll(self, timeout_seconds: float = 1.0) -> ConsumedMessage | None: ...

    async def commit(self, message: ConsumedMessage) -> None: ...

    async def close(self) -> None: ...


class KafkaEventPublisher:
    """Async facade over the production-grade confluent-kafka Producer."""

    def __init__(self, settings: EventIngestionSettings) -> None:
        self._settings = settings
        self._producer: Producer | None = None

    def _get_producer(self) -> Producer:
        if self._producer is None:
            self._producer = Producer(
                {
                    "bootstrap.servers": self._settings.bootstrap_servers,
                    "client.id": self._settings.client_id,
                    "acks": "all",
                    "enable.idempotence": True,
                }
            )
        return self._producer

    async def publish(self, *, topic: str, key: str, value: bytes) -> PublishReceipt:
        return await asyncio.to_thread(self._publish_sync, topic, key, value)

    def _publish_sync(self, topic: str, key: str, value: bytes) -> PublishReceipt:
        producer = self._get_producer()
        delivered: list[Message] = []
        failures: list[BaseException] = []

        def delivery_callback(error: KafkaError | None, message: Message) -> None:
            if error is not None:
                failures.append(KafkaException(error))
            else:
                delivered.append(message)

        try:
            producer.produce(
                topic=topic,
                key=key.encode("utf-8"),
                value=value,
                on_delivery=delivery_callback,
            )
            remaining = producer.flush(10.0)
        except (BufferError, KafkaException) as exc:
            raise BrokerUnavailableError("Kafka publish failed.") from exc
        if remaining or failures or not delivered:
            raise BrokerUnavailableError("Kafka did not acknowledge the event.")
        message = delivered[0]
        partition = message.partition()
        offset = message.offset()
        return PublishReceipt(
            topic=message.topic() or topic,
            partition=partition if partition is not None else -1,
            offset=offset if offset is not None else -1,
        )

    async def close(self) -> None:
        if self._producer is not None:
            await asyncio.to_thread(self._producer.flush, 10.0)


class KafkaEventConsumer:
    """Single-group consumer that exposes explicit commit semantics."""

    def __init__(self, settings: EventIngestionSettings) -> None:
        self._consumer = Consumer(
            {
                "bootstrap.servers": settings.bootstrap_servers,
                "client.id": f"{settings.client_id}-worker",
                "group.id": settings.consumer_group,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }
        )
        self._consumer.subscribe([settings.alerts_topic])

    async def poll(self, timeout_seconds: float = 1.0) -> ConsumedMessage | None:
        message = await asyncio.to_thread(self._consumer.poll, timeout_seconds)
        if message is None:
            return None
        error = message.error()
        if error is not None:
            raise BrokerUnavailableError("Kafka consume failed.") from KafkaException(error)
        raw_key = message.key() or b""
        raw_value = message.value() or b""
        partition = message.partition()
        offset = message.offset()
        return ConsumedMessage(
            topic=message.topic() or "unknown",
            partition=partition if partition is not None else -1,
            offset=offset if offset is not None else -1,
            key=raw_key.decode("utf-8", errors="replace"),
            value=raw_value,
            native_message=message,
        )

    async def commit(self, message: ConsumedMessage) -> None:
        await asyncio.to_thread(
            self._consumer.commit,
            message=message.native_message,
            asynchronous=False,
        )

    async def close(self) -> None:
        await asyncio.to_thread(self._consumer.close)


class InMemoryEventPublisher:
    """Deterministic publisher used by contract tests without a broker."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str, bytes]] = []

    async def publish(self, *, topic: str, key: str, value: bytes) -> PublishReceipt:
        self.messages.append((topic, key, value))
        return PublishReceipt(topic=topic, partition=0, offset=len(self.messages) - 1)

    async def close(self) -> None:
        return None
