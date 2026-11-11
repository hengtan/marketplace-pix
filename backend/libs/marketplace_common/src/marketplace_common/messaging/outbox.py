from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Protocol, Self
from uuid import UUID

from opentelemetry.trace import SpanKind

from marketplace_common.observability.metrics import (
    OUTBOX_PENDING,
    OUTBOX_PUBLISHED,
    OUTBOX_RELAY_ERRORS,
)
from marketplace_common.observability.tracing import context_from_traceparent, get_tracer

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    id: UUID
    topic: str
    key: str
    type: str
    payload: dict[str, Any]
    traceparent: str | None = None


class OutboxStore(Protocol):
    async def fetch_pending(self, limit: int) -> list[OutboxMessage]: ...

    async def count_pending(self) -> int: ...

    async def mark_published(self, ids: list[UUID]) -> None: ...


class MessagePublisher(Protocol):
    async def publish(self, message: OutboxMessage) -> None: ...


class RelayUnitOfWork(Protocol):
    @property
    def outbox_store(self) -> OutboxStore: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


class OutboxRelay:
    def __init__(
        self,
        uow_factory: Callable[[], RelayUnitOfWork],
        publisher: MessagePublisher,
        batch_size: int = 100,
    ) -> None:
        self._uow_factory = uow_factory
        self._publisher = publisher
        self._batch_size = batch_size

    async def run_once(self) -> int:
        async with self._uow_factory() as uow:
            messages = await uow.outbox_store.fetch_pending(self._batch_size)
            published: list[UUID] = []
            try:
                for message in messages:
                    await self._publish(message)
                    published.append(message.id)
            finally:
                if published:
                    await uow.outbox_store.mark_published(published)
                    await uow.commit()
            OUTBOX_PENDING.set(await uow.outbox_store.count_pending())
            return len(published)

    async def _publish(self, message: OutboxMessage) -> None:
        with get_tracer().start_as_current_span(
            f"{message.topic} publish",
            context=context_from_traceparent(message.traceparent),
            kind=SpanKind.PRODUCER,
            attributes={
                "messaging.system": "kafka",
                "messaging.destination.name": message.topic,
                "messaging.message.id": str(message.id),
                "marketplace.event_type": message.type,
            },
        ):
            await self._publisher.publish(message)
        OUTBOX_PUBLISHED.labels(topic=message.topic, event_type=message.type).inc()

    async def run_forever(
        self,
        stop: asyncio.Event,
        poll_interval: float = 0.5,
        error_backoff: float = 2.0,
    ) -> None:
        while not stop.is_set():
            try:
                count = await self.run_once()
            except Exception:
                OUTBOX_RELAY_ERRORS.inc()
                logger.exception("outbox relay failed, backing off")
                await self._sleep(stop, error_backoff)
                continue
            if count == 0:
                await self._sleep(stop, poll_interval)

    @staticmethod
    async def _sleep(stop: asyncio.Event, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=seconds)
