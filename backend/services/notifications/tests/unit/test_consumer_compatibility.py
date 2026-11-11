from uuid import uuid4

import pytest
from marketplace_common.events import golden_payload
from marketplace_common.messaging import IncomingEvent

from notifications.application.handle_event import HandleEvent, HandleResult
from tests.fakes import FakeDatabase, FakeQueue, FakeUow
from tests.helpers import NOW


def incoming(event_type: str, version: int) -> IncomingEvent:
    payload = golden_payload(event_type, version)
    return IncomingEvent(uuid4(), event_type, payload["order_id"], payload, version)


@pytest.mark.parametrize("version", [1, 2])
async def test_notifications_handles_every_order_created_version(version: int) -> None:
    db, queue = FakeDatabase(), FakeQueue()
    handler = HandleEvent(
        lambda: FakeUow(db), queue, base_url="http://shop.test", clock=lambda: NOW
    )
    assert await handler.handle(incoming("OrderCreated", version)) == HandleResult.PROCESSED
    (order,) = db.orders.values()
    assert order.contact.email == "maria@example.com"
    assert order.total_cents == 3980


async def test_notifications_follows_the_whole_golden_lifecycle() -> None:
    db, queue = FakeDatabase(), FakeQueue()
    handler = HandleEvent(
        lambda: FakeUow(db), queue, base_url="http://shop.test", clock=lambda: NOW
    )
    for event_type in ("OrderCreated", "PaymentCreated", "OrderPaid"):
        version = 2 if event_type == "OrderCreated" else 1
        assert await handler.handle(incoming(event_type, version)) == HandleResult.PROCESSED
    assert sorted(db.by_kind()) == ["ORDER_CREATED", "ORDER_PAID", "PIX_READY"]
