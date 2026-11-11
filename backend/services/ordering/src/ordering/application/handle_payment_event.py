from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum
from uuid import UUID

from ordering.application.ports import IncomingEvent, UnitOfWork
from ordering.domain.errors import InvalidStateTransition

logger = logging.getLogger(__name__)

CONSUMER_NAME = "ordering"
HANDLED_TYPES = {"PaymentConfirmed", "PaymentExpired"}


class HandleResult(StrEnum):
    PROCESSED = "PROCESSED"
    DUPLICATE = "DUPLICATE"
    IGNORED = "IGNORED"
    CONFLICT = "CONFLICT"


class HandlePaymentEvent:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def handle(self, event: IncomingEvent) -> HandleResult:
        if event.type not in HANDLED_TYPES:
            return HandleResult.IGNORED
        order_id = UUID(event.payload["order_id"])

        async with self._uow_factory() as uow:
            if not await uow.inbox.claim(event.id, CONSUMER_NAME):
                return HandleResult.DUPLICATE
            order = await uow.orders.get(order_id, lock=True)
            if order is None:
                logger.warning("%s for unknown order %s ignored", event.type, order_id)
                return HandleResult.IGNORED

            try:
                if event.type == "PaymentConfirmed":
                    order.mark_paid()
                else:
                    order.cancel("payment expired")
            except InvalidStateTransition:
                logger.error(
                    "conflict: %s for order %s in status %s (needs manual review or refund)",
                    event.type,
                    order_id,
                    order.status,
                )
                await uow.commit()
                return HandleResult.CONFLICT

            await uow.orders.save(order)
            await uow.outbox.add(order.pull_events())
            await uow.commit()
        return HandleResult.PROCESSED
