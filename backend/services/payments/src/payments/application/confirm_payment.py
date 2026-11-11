from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from payments.application.clock import Clock, utcnow
from payments.application.errors import PaymentNotFound
from payments.application.ports import ChargeStatus, PspGateway, UnitOfWork
from payments.domain.payment import PaymentStatus


class ConfirmResult(StrEnum):
    CONFIRMED = "CONFIRMED"
    ALREADY_CONFIRMED = "ALREADY_CONFIRMED"
    NOT_PAID = "NOT_PAID"


class ConfirmPayment:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        psp: PspGateway,
        clock: Clock = utcnow,
    ) -> None:
        self._uow_factory = uow_factory
        self._psp = psp
        self._clock = clock

    async def execute(self, psp_charge_id: str) -> ConfirmResult:
        async with self._uow_factory() as uow:
            payment = await uow.payments.get_by_psp_charge_id(psp_charge_id, lock=True)
            if payment is None:
                raise PaymentNotFound(psp_charge_id)
            if payment.status is PaymentStatus.CONFIRMED:
                return ConfirmResult.ALREADY_CONFIRMED

            status = await self._psp.get_charge_status(psp_charge_id)
            if status is not ChargeStatus.PAID:
                return ConfirmResult.NOT_PAID

            payment.confirm(self._clock())
            await uow.payments.save(payment)
            await uow.outbox.add(payment.pull_events())
            await uow.commit()
        return ConfirmResult.CONFIRMED
