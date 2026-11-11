from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from enum import StrEnum
from uuid import UUID

from payments.application.clock import Clock, utcnow
from payments.application.ports import IncomingEvent, PspGateway, UnitOfWork
from payments.domain.money import Money
from payments.domain.payment import Payment

CONSUMER_NAME = "payments"


class HandleResult(StrEnum):
    PROCESSED = "PROCESSED"
    DUPLICATE = "DUPLICATE"
    IGNORED = "IGNORED"


class HandleOrderEvent:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        psp: PspGateway,
        ttl: timedelta = timedelta(minutes=30),
        clock: Clock = utcnow,
    ) -> None:
        self._uow_factory = uow_factory
        self._psp = psp
        self._ttl = ttl
        self._clock = clock

    async def handle(self, event: IncomingEvent) -> HandleResult:
        if event.type != "OrderCreated":
            return HandleResult.IGNORED
        order_id = UUID(event.payload["order_id"])
        amount = Money(event.payload["total_cents"], event.payload["currency"])

        async with self._uow_factory() as uow:
            if not await uow.inbox.claim(event.id, CONSUMER_NAME):
                return HandleResult.DUPLICATE
            if await uow.payments.get_by_order(order_id) is not None:
                await uow.commit()
                return HandleResult.DUPLICATE

            charge = await self._psp.create_charge(
                reference=str(order_id), amount=amount, expires_at=self._clock() + self._ttl
            )
            payment = Payment.create(
                order_id, amount, charge.id, charge.pix_code, charge.expires_at
            )
            await uow.payments.add(payment)
            await uow.outbox.add(payment.pull_events())
            await uow.commit()
        return HandleResult.PROCESSED
