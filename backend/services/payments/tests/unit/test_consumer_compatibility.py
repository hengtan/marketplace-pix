from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from marketplace_common.events import golden_payload
from marketplace_common.messaging import IncomingEvent

from payments.application.handle_order_event import HandleOrderEvent, HandleResult
from tests.fakes import FakeDatabase, FakePsp, FakeUow

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def incoming(event_type: str, version: int) -> IncomingEvent:
    payload = golden_payload(event_type, version)
    return IncomingEvent(uuid4(), event_type, payload["order_id"], payload, version)


@pytest.mark.parametrize("version", [1, 2])
async def test_payments_charges_the_right_amount_for_every_order_created_version(
    version: int,
) -> None:
    db, psp = FakeDatabase(), FakePsp()
    handler = HandleOrderEvent(
        lambda: FakeUow(db), psp, ttl=timedelta(minutes=30), clock=lambda: NOW
    )

    assert await handler.handle(incoming("OrderCreated", version)) is HandleResult.PROCESSED

    (payment,) = db.payments.values()
    assert payment.amount.cents == 3980


async def test_payments_reads_order_cancelled_v1() -> None:
    db, psp = FakeDatabase(), FakePsp()
    handler = HandleOrderEvent(
        lambda: FakeUow(db), psp, ttl=timedelta(minutes=30), clock=lambda: NOW
    )
    await handler.handle(incoming("OrderCreated", 2))
    assert await handler.handle(incoming("OrderCancelled", 1)) is HandleResult.PROCESSED
    (payment,) = db.payments.values()
    assert payment.status.value == "CANCELLED"
