from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Sequence
from typing import Any, Protocol

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from opentelemetry.trace import SpanKind, Status, StatusCode

from marketplace_common.messaging.events import IncomingEvent, header_map, to_incoming_event
from marketplace_common.observability.metrics import DLQ_MESSAGES, HANDLER_DURATION
from marketplace_common.observability.tracing import context_from_headers, get_tracer

logger = logging.getLogger(__name__)


class EventHandler(Protocol):
    async def handle(self, event: IncomingEvent) -> Any: ...


class KafkaEventConsumer:
    """Consome um ou mais tópicos com commit manual.

    Se o handler falhar, a mensagem é reprocessada. Depois de `max_attempts` falhas ela vai para
    `<tópico de origem>.dlq` e o consumo segue, para que uma mensagem envenenada não trave a
    partição. Cada mensagem vira um span que continua o trace de quem a publicou.
    """

    def __init__(
        self,
        bootstrap_servers: str,
        topics: str | Sequence[str],
        group_id: str,
        handler: EventHandler,
        error_backoff: float = 2.0,
        max_attempts: int = 10,
    ) -> None:
        self._handler = handler
        self._group_id = group_id
        self._error_backoff = error_backoff
        self._max_attempts = max_attempts
        self._attempts: dict[tuple[str, int, int], int] = {}
        names = [topics] if isinstance(topics, str) else list(topics)
        self._consumer = AIOKafkaConsumer(
            *names,
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
        with get_tracer().start_as_current_span(
            f"{record.topic} process",
            context=context_from_headers(header_map(record)),
            kind=SpanKind.CONSUMER,
            attributes={
                "messaging.system": "kafka",
                "messaging.destination.name": record.topic,
                "messaging.kafka.consumer.group": self._group_id,
                "messaging.kafka.message.offset": record.offset,
                "messaging.message.id": str(event.id),
                "marketplace.event_type": event.type,
            },
        ) as span:
            started = time.perf_counter()
            try:
                await self._handler.handle(event)
            except Exception as error:
                HANDLER_DURATION.labels(self._group_id, event.type, "error").observe(
                    time.perf_counter() - started
                )
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, repr(error)[:200]))
                attempts = self._attempts.get(position, 0) + 1
                if attempts >= self._max_attempts and await self._dead_letter(record, error):
                    span.set_attribute("marketplace.dead_lettered", True)
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
            HANDLER_DURATION.labels(self._group_id, event.type, "success").observe(
                time.perf_counter() - started
            )
        self._attempts.pop(position, None)
        return True

    async def _dead_letter(self, record: Any, error: Exception) -> bool:
        dlq_topic = f"{record.topic}.dlq"
        headers = [
            *(record.headers or []),
            ("dlq_reason", repr(error)[:500].encode()),
            ("dlq_source", f"{record.topic}/{record.partition}/{record.offset}".encode()),
            ("dlq_group", self._group_id.encode()),
        ]
        try:
            await self._dlq_producer.send_and_wait(
                dlq_topic, key=record.key, value=record.value, headers=headers
            )
        except Exception:
            logger.exception("could not publish to %s, will keep retrying", dlq_topic)
            return False
        DLQ_MESSAGES.labels(record.topic, self._group_id).inc()
        logger.error(
            "event sent to %s after %d attempts (%s/%s/%s): %r",
            dlq_topic,
            self._max_attempts,
            record.topic,
            record.partition,
            record.offset,
            error,
        )
        return True
