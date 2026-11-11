from __future__ import annotations

from collections.abc import Callable, Collection
from uuid import UUID

from marketplace_common.security import Principal, Scope

from inventory.application.errors import NotStockOwner
from inventory.application.ports import UnitOfWork
from inventory.domain.stock import Stock


class GetStock:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], list_limit: int = 500) -> None:
        self._uow_factory = uow_factory
        self._list_limit = list_limit

    async def execute(self, product_ids: Collection[UUID]) -> list[Stock]:
        async with self._uow_factory() as uow:
            found = await uow.stocks.get_many(product_ids)
        ordered = list(dict.fromkeys(product_ids))
        return [found.get(pid) or Stock(pid) for pid in ordered]

    async def list_all(self) -> list[Stock]:
        async with self._uow_factory() as uow:
            return await uow.stocks.list_all(self._list_limit)

    async def list_by_merchant(self, merchant_id: UUID) -> list[Stock]:
        async with self._uow_factory() as uow:
            return await uow.stocks.list_by_merchant(merchant_id, self._list_limit)


class SetStock:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def execute(
        self, product_id: UUID, available: int, principal: Principal | None = None
    ) -> Stock:
        async with self._uow_factory() as uow:
            found = await uow.stocks.get_many([product_id], lock=True)
            stock = found.get(product_id) or Stock(product_id)
            if principal is not None and not self._may_write(principal, found.get(product_id)):
                raise NotStockOwner(str(product_id))
            stock.set_available(available)
            await uow.stocks.save(stock)
            await uow.commit()
        return stock

    @staticmethod
    def _may_write(principal: Principal, current: Stock | None) -> bool:
        if principal.can(Scope.STOCK_WRITE_ANY):
            return True
        if not principal.can(Scope.STOCK_WRITE_OWN) or current is None:
            return False
        return current.merchant_id is not None and principal.owns_merchant(current.merchant_id)
