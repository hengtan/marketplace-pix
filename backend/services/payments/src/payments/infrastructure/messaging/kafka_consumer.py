from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any, Protocol
from uuid import UUID

from aiokafka import AIOKafkaConsumer, TopicPartition

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
    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        group_id: str,
        handler: EventHandler,
        error_backoff: float = 2.0,
    ) -> None:
        self._handler = handler
        self._error_backoff = error_backoff
        self._consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )

    async def start(self) -> None:
        await self._consumer.start()

    async def stop(self) -> None:
        await self._consumer.stop()

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
        try:
            await self._handler.handle(event)
        except Exception:
            logger.exception("handler failed for event %s, will retry", event.id)
            self._consumer.seek(partition, record.offset)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=self._error_backoff)
            return False
        return True
