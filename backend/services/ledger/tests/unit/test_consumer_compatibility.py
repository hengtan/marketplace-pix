from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from marketplace_common.events import golden_payload
from marketplace_common.messaging import IncomingEvent

from ledger.application.handle_order_event import HandleOrderEvent
from ledger.application.handle_payment_event import HandlePaymentEvent
from ledger.application.results import HandleResult
from tests.fakes import FakeDatabase, FakeUow


def incoming(event_type: str, version: int) -> IncomingEvent:
    payload = golden_payload(event_type, version)
    return IncomingEvent(uuid4(), event_type, payload["order_id"], payload, version)


@pytest.mark.parametrize("order_version", [1, 2])
async def test_ledger_posts_the_sale_from_every_published_order_created_version(
    order_version: int,
) -> None:
    db = FakeDatabase()
    orders = HandleOrderEvent(lambda: FakeUow(db))
    payments = HandlePaymentEvent(lambda: FakeUow(db))

    assert await orders.handle(incoming("OrderCreated", order_version)) is HandleResult.PROCESSED
    assert await payments.handle(incoming("PaymentConfirmed", 1)) is HandleResult.PROCESSED

    (transaction,) = db.transactions.values()
    assert transaction.total_debits.cents == 3980
    assert transaction.platform_fee.cents == 398
    assert transaction.order_id == UUID(golden_payload("OrderCreated", order_version)["order_id"])
