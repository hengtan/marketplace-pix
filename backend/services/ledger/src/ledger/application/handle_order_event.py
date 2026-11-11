from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from ledger.application.clock import Clock, utcnow
from ledger.application.ports import IncomingEvent, UnitOfWork
from ledger.application.results import HandleResult
from ledger.domain.errors import DomainError
from ledger.domain.money import Money
from ledger.domain.order_projection import OrderProjection, ProjectedItem

CONSUMER_NAME = "ledger-orders"

logger = logging.getLogger(__name__)


def parse_order_created(payload: dict[str, Any], received_at: datetime) -> OrderProjection:
    currency = payload["currency"]
    created_at = payload.get("occurred_at")
    return OrderProjection(
        order_id=UUID(payload["order_id"]),
        currency=currency,
        items=tuple(
            ProjectedItem(
                product_id=UUID(item["product_id"]),
                merchant_id=UUID(item["merchant_id"]),
                quantity=item["quantity"],
                unit_price=Money(item["unit_price_cents"], currency),
            )
            for item in payload["items"]
        ),
        created_at=datetime.fromisoformat(created_at) if created_at else received_at,
    )


class HandleOrderEvent:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], clock: Clock = utcnow) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def handle(self, event: IncomingEvent) -> HandleResult:
        if event.type != "OrderCreated":
            return HandleResult.IGNORED
        try:
            projection = parse_order_created(event.payload, self._clock())
        except (KeyError, ValueError, TypeError, DomainError):
            logger.error("OrderCreated %s is malformed and was rejected", event.id)
            return HandleResult.REJECTED

        async with self._uow_factory() as uow:
            if not await uow.inbox.claim(event.id, CONSUMER_NAME):
                return HandleResult.DUPLICATE
            created = await uow.orders.add(projection)
            await uow.commit()
        return HandleResult.PROCESSED if created else HandleResult.DUPLICATE
