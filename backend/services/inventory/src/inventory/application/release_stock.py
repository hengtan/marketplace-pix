from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import UUID

from inventory.application.common import Delivery, Outcome
from inventory.application.ports import UnitOfWork
from inventory.domain.reservation import ReservationStatus

logger = logging.getLogger(__name__)


class ReleaseStock:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def execute(
        self, order_id: UUID, reason: str, delivery: Delivery | None = None
    ) -> Outcome:
        async with self._uow_factory() as uow:
            if delivery and not await uow.inbox.claim(delivery.event_id, delivery.consumer):
                return Outcome.DUPLICATE
            reservation = await uow.reservations.get_by_order(order_id, lock=True)
            if reservation is None or reservation.status is not ReservationStatus.RESERVED:
                logger.info("nothing to release for order %s (%s)", order_id, reason)
                await uow.commit()
                return Outcome.IGNORED

            stocks = await uow.stocks.get_many(reservation.product_ids, lock=True)
            reservation.release(stocks, reason)
            for product_id in reservation.product_ids:
                await uow.stocks.save(stocks[product_id])
            await uow.reservations.save(reservation)
            await uow.outbox.add(reservation.pull_events())
            await uow.commit()
        return Outcome.PROCESSED
