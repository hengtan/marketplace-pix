from __future__ import annotations

from collections.abc import Callable, Collection
from uuid import UUID

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


class SetStock:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def execute(self, product_id: UUID, available: int) -> Stock:
        async with self._uow_factory() as uow:
            found = await uow.stocks.get_many([product_id], lock=True)
            stock = found.get(product_id) or Stock(product_id)
            stock.set_available(available)
            await uow.stocks.save(stock)
            await uow.commit()
        return stock
