from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import UUID

from marketplace_common.messaging import IncomingEvent

from ledger.application.clock import Clock, utcnow
from ledger.application.errors import OrderProjectionNotFound
from ledger.application.ports import UnitOfWork
from ledger.application.results import HandleResult
from ledger.domain.errors import DomainError
from ledger.domain.money import Money
from ledger.domain.posting import build_payment_transaction, build_reversal_transaction
from ledger.domain.split import DEFAULT_FEE_BPS
from ledger.domain.transaction import TransactionKind

CONSUMER_NAME = "ledger-payments"

logger = logging.getLogger(__name__)


class HandlePaymentEvent:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        fee_bps: int = DEFAULT_FEE_BPS,
        clock: Clock = utcnow,
    ) -> None:
        self._uow_factory = uow_factory
        self._fee_bps = fee_bps
        self._clock = clock

    async def handle(self, event: IncomingEvent) -> HandleResult:
        if event.type not in {"PaymentConfirmed", "PaymentRefunded"}:
            return HandleResult.IGNORED
        reversal = event.type == "PaymentRefunded"
        try:
            order_id = UUID(event.payload["order_id"])
            payment_id = UUID(event.payload["payment_id"])
            amount = Money(event.payload["amount_cents"], event.payload["currency"])
        except (KeyError, ValueError, TypeError, DomainError):
            logger.error("%s %s is malformed and was rejected", event.type, event.id)
            return HandleResult.REJECTED

        async with self._uow_factory() as uow:
            if not await uow.inbox.claim(event.id, CONSUMER_NAME):
                return HandleResult.DUPLICATE
            projection = await uow.orders.get(order_id)
            if projection is None:
                raise OrderProjectionNotFound(f"order {order_id} is not projected yet")
            if reversal and not await uow.ledger.has_transaction(
                order_id, TransactionKind.PAYMENT.value
            ):
                raise OrderProjectionNotFound(f"payment of order {order_id} is not posted yet")
            build = build_reversal_transaction if reversal else build_payment_transaction
            try:
                transaction = build(projection, payment_id, amount, self._clock(), self._fee_bps)
            except DomainError:
                logger.exception("payment %s cannot be posted for order %s", payment_id, order_id)
                return HandleResult.REJECTED
            if not await uow.ledger.add_transaction(transaction):
                await uow.commit()
                return HandleResult.DUPLICATE
            await uow.outbox.add(transaction.pull_events())
            await uow.commit()
        return HandleResult.PROCESSED
