from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from ordering.application.errors import OrderNotFound
from ordering.application.ports import UnitOfWork
from ordering.domain.order import Order


class GetOrder:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def execute(self, order_id: UUID) -> Order:
        async with self._uow_factory() as uow:
            order = await uow.orders.get(order_id)
        if order is None:
            raise OrderNotFound(str(order_id))
        return order
