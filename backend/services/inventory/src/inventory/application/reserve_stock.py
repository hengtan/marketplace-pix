from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import timedelta
from uuid import UUID

from inventory.application.clock import Clock, utcnow
from inventory.application.common import Delivery, Outcome
from inventory.application.ports import UnitOfWork
from inventory.domain.reservation import (
    Reservation,
    ReservationItem,
    ReservationStatus,
    merge_items,
)


class ReserveStock:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        ttl: timedelta = timedelta(minutes=35),
        clock: Clock = utcnow,
    ) -> None:
        self._uow_factory = uow_factory
        self._ttl = ttl
        self._clock = clock

    async def execute(
        self,
        order_id: UUID,
        items: Sequence[ReservationItem],
        delivery: Delivery | None = None,
    ) -> Outcome:
        merged = merge_items(items)
        product_ids = sorted({item.product_id for item in merged})
        async with self._uow_factory() as uow:
            if delivery and not await uow.inbox.claim(delivery.event_id, delivery.consumer):
                return Outcome.DUPLICATE
            if await uow.reservations.get_by_order(order_id) is not None:
                await uow.commit()
                return Outcome.DUPLICATE

            stocks = await uow.stocks.get_many(product_ids, lock=True)
            if await uow.reservations.get_by_order(order_id) is not None:
                await uow.commit()
                return Outcome.DUPLICATE

            reservation = Reservation.place(order_id, merged, stocks, self._clock(), self._ttl)
            if reservation.status is ReservationStatus.RESERVED:
                for product_id in product_ids:
                    await uow.stocks.save(stocks[product_id])
            await uow.reservations.add(reservation)
            await uow.outbox.add(reservation.pull_events())
            await uow.commit()
        return Outcome.PROCESSED
