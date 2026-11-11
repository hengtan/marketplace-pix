from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum
from uuid import UUID

from marketplace_common.messaging import IncomingEvent

from ordering.application.ports import UnitOfWork
from ordering.domain.errors import InvalidStateTransition
from ordering.domain.events import PaymentRefundRequested
from ordering.domain.order import Order, OrderStatus
from ordering.saga_metrics import SAGA_LATE_PAYMENTS

logger = logging.getLogger(__name__)

CONSUMER_NAME = "ordering"
HANDLED_TYPES = {"PaymentConfirmed", "PaymentExpired", "StockRejected"}
CANCEL_REASONS = {"PaymentExpired": "payment expired", "StockRejected": "out of stock"}


LATE_PAYMENT_REASON = "order cancelled before payment"
AUDIT_LATE_PAYMENT = "LATE_PAYMENT"


class HandleResult(StrEnum):
    PROCESSED = "PROCESSED"
    DUPLICATE = "DUPLICATE"
    IGNORED = "IGNORED"
    CONFLICT = "CONFLICT"
    REFUND_REQUESTED = "REFUND_REQUESTED"


class HandleSagaEvent:
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
                    order.cancel(CANCEL_REASONS[event.type])
            except InvalidStateTransition:
                if event.type == "PaymentConfirmed" and order.status is OrderStatus.CANCELLED:
                    return await self._refund_late_payment(uow, order, event)
                logger.error(
                    "conflict: %s for order %s in status %s (needs manual review)",
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

    async def _refund_late_payment(
        self, uow: UnitOfWork, order: Order, event: IncomingEvent
    ) -> HandleResult:
        payload = event.payload
        payment_id = UUID(payload["payment_id"])
        amount_cents = int(payload["amount_cents"])
        currency = str(payload["currency"])
        first_time = await uow.audit.record(
            order.id,
            AUDIT_LATE_PAYMENT,
            payment_id,
            {
                "event_id": str(event.id),
                "amount_cents": amount_cents,
                "currency": currency,
                "order_status": order.status.value,
                "cancel_reason": order.cancel_reason,
            },
        )
        if first_time:
            await uow.outbox.add(
                [
                    PaymentRefundRequested(
                        order_id=order.id,
                        payment_id=payment_id,
                        amount_cents=amount_cents,
                        currency=currency,
                        reason=LATE_PAYMENT_REASON,
                    )
                ]
            )
            SAGA_LATE_PAYMENTS.inc()
            logger.warning(
                "payment %s confirmed after order %s was cancelled (%s), refund requested",
                payment_id,
                order.id,
                order.cancel_reason,
            )
        await uow.commit()
        return HandleResult.REFUND_REQUESTED
