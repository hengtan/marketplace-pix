from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import UUID

from inventory.application.common import Delivery, Outcome
from inventory.application.ports import UnitOfWork
from inventory.domain.stock import Stock

logger = logging.getLogger(__name__)


class RegisterProduct:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def execute(
        self, product_id: UUID, merchant_id: UUID, delivery: Delivery | None = None
    ) -> Outcome:
        async with self._uow_factory() as uow:
            if delivery and not await uow.inbox.claim(delivery.event_id, delivery.consumer):
                return Outcome.DUPLICATE
            existing = (await uow.stocks.get_many([product_id], lock=True)).get(product_id)
            if existing is None:
                await uow.stocks.save(Stock(product_id, 0, merchant_id=merchant_id))
            elif existing.merchant_id is None or not existing.active:
                if existing.merchant_id is None:
                    existing.merchant_id = merchant_id
                existing.active = True
                await uow.stocks.save(existing)
            else:
                logger.info("stock of product %s already registered", product_id)
                await uow.commit()
                return Outcome.IGNORED
            await uow.commit()
        return Outcome.PROCESSED

    async def deactivate(self, product_id: UUID, delivery: Delivery | None = None) -> Outcome:
        async with self._uow_factory() as uow:
            if delivery and not await uow.inbox.claim(delivery.event_id, delivery.consumer):
                return Outcome.DUPLICATE
            existing = (await uow.stocks.get_many([product_id], lock=True)).get(product_id)
            if existing is None or not existing.active:
                await uow.commit()
                return Outcome.IGNORED
            existing.active = False
            await uow.stocks.save(existing)
            await uow.commit()
        return Outcome.PROCESSED
