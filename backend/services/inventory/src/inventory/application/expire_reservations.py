from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

from inventory.application.clock import Clock, utcnow
from inventory.application.ports import UnitOfWork

logger = logging.getLogger(__name__)

EXPIRED_REASON = "reservation_expired"


class ExpireReservations:
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
            due = await uow.reservations.fetch_expired(now, self._batch_size)
            if not due:
                return 0
            product_ids = sorted({pid for reservation in due for pid in reservation.product_ids})
            stocks = await uow.stocks.get_many(product_ids, lock=True)
            for reservation in due:
                reservation.release(stocks, EXPIRED_REASON)
                await uow.reservations.save(reservation)
                await uow.outbox.add(reservation.pull_events())
            for product_id in product_ids:
                await uow.stocks.save(stocks[product_id])
            await uow.commit()
        return len(due)

    async def run_forever(
        self, stop: asyncio.Event, interval: float = 30.0, error_backoff: float = 5.0
    ) -> None:
        while not stop.is_set():
            wait = interval
            try:
                await self.run_once()
            except Exception:
                logger.exception("reservation expiry job failed, backing off")
                wait = error_backoff
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=wait)
