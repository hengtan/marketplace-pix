from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any, Protocol
from uuid import UUID

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition

from payments.application.ports import IncomingEvent

logger = logging.getLogger(__name__)


class EventHandler(Protocol):
    async def handle(self, event: IncomingEvent) -> Any: ...


def to_incoming_event(record: Any) -> IncomingEvent | None:
    try:
        headers = {k: v.decode() for k, v in (record.headers or [])}
        return IncomingEvent(
            id=UUID(headers["event_id"]),
            type=headers["event_type"],
            key=record.key.decode(),
            payload=json.loads(record.value),
        )
    except (KeyError, ValueError, AttributeError):
        logger.error("malformed message skipped (offset %s)", getattr(record, "offset", "?"))
        return None


class KafkaEventConsumer:
    """Consome um tópico com commit manual.

    Se o handler falhar, a mensagem é reprocessada. Depois de `max_attempts` falhas ela vai
    para `<tópico>.dlq` e o consumo segue, para que uma mensagem envenenada não trave a partição.
    """

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        group_id: str,
        handler: EventHandler,
        error_backoff: float = 2.0,
        max_attempts: int = 10,
        dlq_topic: str | None = None,
    ) -> None:
        self._handler = handler
        self._group_id = group_id
        self._error_backoff = error_backoff
        self._max_attempts = max_attempts
        self._dlq_topic = dlq_topic or f"{topic}.dlq"
        self._attempts: dict[tuple[str, int, int], int] = {}
        self._consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        self._dlq_producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers, acks="all")

    async def start(self) -> None:
        await self._consumer.start()
        await self._dlq_producer.start()

    async def stop(self) -> None:
        await self._consumer.stop()
        await self._dlq_producer.stop()

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            batches = await self._consumer.getmany(timeout_ms=1000, max_records=1)
            for partition, records in batches.items():
                for record in records:
                    if not await self._process(partition, record, stop):
                        break
                    await self._consumer.commit()

    async def _process(self, partition: TopicPartition, record: Any, stop: asyncio.Event) -> bool:
        event = to_incoming_event(record)
        if event is None:
            return True
        position = (partition.topic, partition.partition, record.offset)
        try:
            await self._handler.handle(event)
        except Exception as error:
            attempts = self._attempts.get(position, 0) + 1
            if attempts >= self._max_attempts and await self._dead_letter(record, error):
                self._attempts.pop(position, None)
                return True
            self._attempts[position] = attempts
            logger.exception(
                "handler failed for event %s (attempt %d/%d), will retry",
                event.id,
                attempts,
                self._max_attempts,
            )
            self._consumer.seek(partition, record.offset)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._error_backoff)
            return False
        self._attempts.pop(position, None)
        return True

    async def _dead_letter(self, record: Any, error: Exception) -> bool:
        headers = [
            *(record.headers or []),
            ("dlq_reason", repr(error)[:500].encode()),
            ("dlq_source", f"{record.topic}/{record.partition}/{record.offset}".encode()),
            ("dlq_group", self._group_id.encode()),
        ]
        try:
            await self._dlq_producer.send_and_wait(
                self._dlq_topic, key=record.key, value=record.value, headers=headers
            )
        except Exception:
            logger.exception("could not publish to %s, will keep retrying", self._dlq_topic)
            return False
        logger.error(
            "event sent to %s after %d attempts (%s/%s/%s): %r",
            self._dlq_topic,
            self._max_attempts,
            record.topic,
            record.partition,
            record.offset,
            error,
        )
        return True
