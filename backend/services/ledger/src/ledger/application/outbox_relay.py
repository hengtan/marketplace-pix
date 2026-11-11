from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from uuid import UUID

from ledger.application.ports import MessagePublisher, RelayUnitOfWork

logger = logging.getLogger(__name__)


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
                    await self._publisher.publish(message)
                    published.append(message.id)
            finally:
                if published:
                    await uow.outbox_store.mark_published(published)
                    await uow.commit()
            return len(published)

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
                logger.exception("outbox relay failed, backing off")
                await self._sleep(stop, error_backoff)
                continue
            if count == 0:
                await self._sleep(stop, poll_interval)

    @staticmethod
    async def _sleep(stop: asyncio.Event, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=seconds)
