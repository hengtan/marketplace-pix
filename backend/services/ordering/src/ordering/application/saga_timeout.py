from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import timedelta

from ordering.application.clock import Clock, utcnow
from ordering.application.ports import UnitOfWork
from ordering.domain.order import SAGA_TIMEOUT_REASON
from ordering.saga_metrics import SAGA_TIMEOUTS

logger = logging.getLogger(__name__)

AUDIT_TIMEOUT = "SAGA_TIMEOUT"


class SagaTimeoutManager:
    """Process manager: cancela o pedido parado em PENDING além do prazo da saga.

    O cancelamento emite `OrderCancelled` e as compensações acontecem por reação: payments
    cancela a cobrança e inventory libera a reserva. O varredor é idempotente (só vê pedidos
    PENDING, trava a linha com SKIP LOCKED e o `cancel` do agregado não repete efeito), então
    roda em várias réplicas e pode ser reexecutado sem emitir um segundo evento.
    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        timeout: timedelta,
        batch_size: int = 100,
        clock: Clock = utcnow,
    ) -> None:
        self._uow_factory = uow_factory
        self._timeout = timeout
        self._batch_size = batch_size
        self._clock = clock

    async def run_once(self) -> int:
        now = self._clock()
        cancelled = 0
        async with self._uow_factory() as uow:
            stuck = await uow.orders.fetch_stuck_pending(now - self._timeout, self._batch_size)
            for order in stuck:
                order.cancel(SAGA_TIMEOUT_REASON)
                await uow.orders.save(order)
                await uow.outbox.add(order.pull_events())
                await uow.audit.record(
                    order.id,
                    AUDIT_TIMEOUT,
                    None,
                    {
                        "created_at": order.created_at.isoformat() if order.created_at else None,
                        "timeout_seconds": self._timeout.total_seconds(),
                        "cancelled_at": now.isoformat(),
                    },
                )
                cancelled += 1
            if stuck:
                await uow.commit()
        if cancelled:
            SAGA_TIMEOUTS.inc(cancelled)
            logger.warning("saga timeout cancelled %d stuck orders", cancelled)
        return cancelled

    async def run_forever(
        self, stop: asyncio.Event, interval: float = 30.0, error_backoff: float = 10.0
    ) -> None:
        while not stop.is_set():
            wait = interval
            try:
                await self.run_once()
            except Exception:
                logger.exception("saga timeout sweep failed, backing off")
                wait = error_backoff
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=wait)
