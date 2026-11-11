from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from ordering.application.ports import OwnerScope, UnitOfWork
from ordering.domain.order import Order

MAX_PAGE_SIZE = 50


@dataclass(frozen=True, slots=True)
class OrderPage:
    items: list[Order]
    total: int
    page: int
    page_size: int


class ListOrders:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def execute(
        self,
        customer_id: UUID,
        page: int = 1,
        page_size: int = 20,
        scope: OwnerScope = OwnerScope.GUEST,
    ) -> OrderPage:
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        async with self._uow_factory() as uow:
            items, total = await uow.orders.list_by_customer(customer_id, page, page_size, scope)
        return OrderPage(items, total, page, page_size)

    async def for_merchant(
        self, merchant_id: UUID, page: int = 1, page_size: int = 20
    ) -> OrderPage:
        page = max(page, 1)
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        async with self._uow_factory() as uow:
            items, total = await uow.orders.list_by_merchant(merchant_id, page, page_size)
        return OrderPage(items, total, page, page_size)
