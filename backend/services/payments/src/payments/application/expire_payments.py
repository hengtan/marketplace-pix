from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

from payments.application.clock import Clock, utcnow
from payments.application.ports import PspGateway, UnitOfWork
from payments.interface.metrics import PSP_CANCEL_REFUSED

logger = logging.getLogger(__name__)


class ExpirePayments:
    """Expira as cobranças vencidas. Antes de marcar como expirada, cancela a cobrança no PSP para
    que um PIX vencido não possa mais ser pago. Se o PSP recusa (cobrança já paga) o pagamento
    segue pendente para o webhook confirmar; se o PSP falha, tenta de novo na próxima rodada."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        psp: PspGateway,
        clock: Clock = utcnow,
        batch_size: int = 100,
    ) -> None:
        self._uow_factory = uow_factory
        self._psp = psp
        self._clock = clock
        self._batch_size = batch_size

    async def run_once(self) -> int:
        now = self._clock()
        expired = 0
        async with self._uow_factory() as uow:
            due = await uow.payments.fetch_expired(now, self._batch_size)
            for payment in due:
                if not await self._cancel_at_psp(payment.psp_charge_id):
                    continue
                payment.expire(now)
                await uow.payments.save(payment)
                await uow.outbox.add(payment.pull_events())
                expired += 1
            if expired:
                await uow.commit()
        return expired

    async def _cancel_at_psp(self, charge_id: str) -> bool:
        try:
            cancelled = await self._psp.cancel_charge(charge_id)
        except Exception:
            logger.exception("could not cancel charge %s at the PSP, will retry", charge_id)
            return False
        if not cancelled:
            PSP_CANCEL_REFUSED.inc()
            logger.warning("PSP refused to cancel the expired charge %s: it may be paid", charge_id)
        return cancelled

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
