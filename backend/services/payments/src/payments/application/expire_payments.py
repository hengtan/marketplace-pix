from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

from payments.application.clock import Clock, utcnow
from payments.application.ports import UnitOfWork

logger = logging.getLogger(__name__)


class ExpirePayments:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        clock: Clock = utcnow,
        batch_size: int = 100,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._batch_size = batch_size

    async def run_once(self) -> int:
        now = self._clock()
        async with self._uow_factory() as uow:
            due = await uow.payments.fetch_expired(now, self._batch_size)
            for payment in due:
                payment.expire(now)
                await uow.payments.save(payment)
                await uow.outbox.add(payment.pull_events())
            if due:
                await uow.commit()
        return len(due)

    async def run_forever(
        self, stop: asyncio.Event, interval: float = 5.0, error_backoff: float = 5.0
    ) -> None:
        while not stop.is_set():
            wait = interval
            try:
                await self.run_once()
            except Exception:
                logger.exception("expiry job failed, backing off")
                wait = error_backoff
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=wait)
