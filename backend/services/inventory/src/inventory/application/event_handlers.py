from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

from marketplace_common.messaging import IncomingEvent

from inventory.application.clock import Clock, utcnow
from inventory.application.commit_stock import CommitStock
from inventory.application.common import Delivery, Outcome
from inventory.application.ports import UnitOfWork
from inventory.application.release_stock import ReleaseStock
from inventory.application.reserve_stock import ReserveStock
from inventory.domain.reservation import ReservationItem

logger = logging.getLogger(__name__)

ORDERS_CONSUMER = "inventory-orders"
PAYMENTS_CONSUMER = "inventory-payments"


def _parse_items(payload: dict[str, object]) -> list[ReservationItem]:
    raw_items = payload["items"]
    if not isinstance(raw_items, list):
        raise TypeError("items must be a list")
    return [ReservationItem(UUID(str(i["product_id"])), int(i["quantity"])) for i in raw_items]


class HandleOrderEvent:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        ttl: timedelta = timedelta(minutes=35),
        clock: Clock = utcnow,
    ) -> None:
        self._reserve = ReserveStock(uow_factory, ttl, clock)
        self._release = ReleaseStock(uow_factory)

    async def handle(self, event: IncomingEvent) -> Outcome:
        delivery = Delivery(event.id, ORDERS_CONSUMER)
        if event.type == "OrderCreated":
            try:
                order_id = UUID(str(event.payload["order_id"]))
                items = _parse_items(event.payload)
            except (KeyError, ValueError, TypeError):
                logger.error("invalid OrderCreated payload skipped (event %s)", event.id)
                return Outcome.IGNORED
            return await self._reserve.execute(order_id, items, delivery)
        if event.type == "OrderCancelled":
            return await self._release.execute(_order_id(event), "order_cancelled", delivery)
        return Outcome.IGNORED


class HandlePaymentEvent:
    RELEASE_REASONS = {
        "PaymentExpired": "payment_expired",
        "PaymentCancelled": "payment_cancelled",
    }

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._commit = CommitStock(uow_factory)
        self._release = ReleaseStock(uow_factory)

    async def handle(self, event: IncomingEvent) -> Outcome:
        delivery = Delivery(event.id, PAYMENTS_CONSUMER)
        if event.type == "PaymentConfirmed":
            return await self._commit.execute(_order_id(event), delivery)
        reason = self.RELEASE_REASONS.get(event.type)
        if reason is not None:
            return await self._release.execute(_order_id(event), reason, delivery)
        return Outcome.IGNORED


def _order_id(event: IncomingEvent) -> UUID:
    return UUID(str(event.payload["order_id"]))
