from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from payments.application.errors import PaymentNotFound
from payments.application.ports import UnitOfWork
from payments.domain.payment import Payment


class GetPaymentByOrder:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def execute(self, order_id: UUID) -> Payment:
        async with self._uow_factory() as uow:
            payment = await uow.payments.get_by_order(order_id)
        if payment is None:
            raise PaymentNotFound(str(order_id))
        return payment
