from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from enum import StrEnum
from uuid import UUID

from marketplace_common.messaging import IncomingEvent

from payments.application.clock import Clock, utcnow
from payments.application.ports import PspGateway, UnitOfWork
from payments.domain.errors import InvalidStateTransition
from payments.domain.money import Money
from payments.domain.payment import Payment, PaymentStatus

logger = logging.getLogger(__name__)

CONSUMER_NAME = "payments"


class HandleResult(StrEnum):
    PROCESSED = "PROCESSED"
    DUPLICATE = "DUPLICATE"
    IGNORED = "IGNORED"
    CONFLICT = "CONFLICT"
    REFUNDED = "REFUNDED"


class HandleOrderEvent:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        psp: PspGateway,
        ttl: timedelta = timedelta(minutes=30),
        clock: Clock = utcnow,
    ) -> None:
        self._uow_factory = uow_factory
        self._psp = psp
        self._ttl = ttl
        self._clock = clock

    async def handle(self, event: IncomingEvent) -> HandleResult:
        if event.type == "OrderCancelled":
            return await self._handle_order_cancelled(event)
        if event.type == "PaymentRefundRequested":
            return await self._handle_refund_requested(event)
        if event.type != "OrderCreated":
            return HandleResult.IGNORED
        order_id = UUID(event.payload["order_id"])
        amount = Money(event.payload["total_cents"], event.payload["currency"])

        async with self._uow_factory() as uow:
            if not await uow.inbox.claim(event.id, CONSUMER_NAME):
                return HandleResult.DUPLICATE
            if await uow.payments.get_by_order(order_id) is not None:
                await uow.commit()
                return HandleResult.DUPLICATE

            charge = await self._psp.create_charge(
                reference=str(order_id), amount=amount, expires_at=self._clock() + self._ttl
            )
            payment = Payment.create(
                order_id, amount, charge.id, charge.pix_code, charge.expires_at
            )
            await uow.payments.add(payment)
            await uow.outbox.add(payment.pull_events())
            await uow.commit()
        return HandleResult.PROCESSED

    async def _handle_refund_requested(self, event: IncomingEvent) -> HandleResult:
        order_id = UUID(event.payload["order_id"])
        reason = str(event.payload.get("reason", "refund requested"))
        async with self._uow_factory() as uow:
            if not await uow.inbox.claim(event.id, CONSUMER_NAME):
                return HandleResult.DUPLICATE
            payment = await uow.payments.get_by_order(order_id, lock=True)
            if payment is None:
                logger.error("refund requested for order %s without a payment", order_id)
                await uow.commit()
                return HandleResult.IGNORED
            if payment.status is PaymentStatus.REFUNDED:
                await uow.commit()
                return HandleResult.DUPLICATE
            if payment.status is not PaymentStatus.CONFIRMED:
                logger.error(
                    "refund requested for order %s but its payment is %s: nothing to refund",
                    order_id,
                    payment.status,
                )
                await uow.commit()
                return HandleResult.IGNORED
            if not await self._psp.refund_charge(payment.psp_charge_id):
                raise RuntimeError(f"PSP did not refund charge {payment.psp_charge_id}")
            payment.refund(reason)
            await uow.payments.save(payment)
            await uow.outbox.add(payment.pull_events())
            await uow.commit()
        return HandleResult.REFUNDED

    async def _handle_order_cancelled(self, event: IncomingEvent) -> HandleResult:
        order_id = UUID(event.payload["order_id"])
        async with self._uow_factory() as uow:
            if not await uow.inbox.claim(event.id, CONSUMER_NAME):
                return HandleResult.DUPLICATE
            payment = await uow.payments.get_by_order(order_id, lock=True)
            if payment is None:
                return HandleResult.IGNORED
            try:
                payment.cancel()
            except InvalidStateTransition:
                logger.error(
                    "order %s cancelled but its payment is confirmed: refund needed", order_id
                )
                await uow.commit()
                return HandleResult.CONFLICT

            events = payment.pull_events()
            if events:
                if not await self._psp.cancel_charge(payment.psp_charge_id):
                    logger.error(
                        "PSP refused to cancel charge %s: it may be paid", payment.psp_charge_id
                    )
                    await uow.commit()
                    return HandleResult.CONFLICT
                await uow.payments.save(payment)
                await uow.outbox.add(events)
            await uow.commit()
        return HandleResult.PROCESSED
