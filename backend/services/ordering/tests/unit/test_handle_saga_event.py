from uuid import UUID, uuid4

import pytest
from marketplace_common.messaging import IncomingEvent

from ordering.application.handle_saga_event import HandleResult, HandleSagaEvent
from ordering.domain.events import (
    OrderCancelled,
    OrderCreated,
    OrderPaid,
    PaymentRefundRequested,
)
from ordering.domain.money import Money
from ordering.domain.order import Order, OrderItem, OrderStatus
from tests.fakes import FakeDatabase, FakeUow


def payment_event(order_id: UUID, type_: str = "PaymentConfirmed", event_id=None) -> IncomingEvent:
    return IncomingEvent(
        id=event_id or uuid4(),
        type=type_,
        key=str(order_id),
        payload={
            "order_id": str(order_id),
            "payment_id": str(uuid4()),
            "amount_cents": 3980,
            "currency": "BRL",
        },
    )


@pytest.fixture
def db():
    return FakeDatabase()


@pytest.fixture
def order(db):
    order = Order.create(
        uuid4(), [OrderItem(uuid4(), uuid4(), 2, Money(1990))], "Maria Souza", "maria@example.com"
    )
    order.pull_events()
    db.orders[order.id] = order
    return order


@pytest.fixture
def handler(db):
    return HandleSagaEvent(lambda: FakeUow(db))


async def test_payment_confirmed_marks_order_paid_and_emits_event(handler, db, order):
    assert await handler.handle(payment_event(order.id)) is HandleResult.PROCESSED

    assert db.orders[order.id].status is OrderStatus.PAID
    assert [type(e) for e in db.events] == [OrderPaid]


async def test_payment_expired_cancels_order_with_reason(handler, db, order):
    result = await handler.handle(payment_event(order.id, "PaymentExpired"))

    assert result is HandleResult.PROCESSED
    assert db.orders[order.id].status is OrderStatus.CANCELLED
    (event,) = db.events
    assert isinstance(event, OrderCancelled) and event.reason == "payment expired"


async def test_same_event_delivered_twice_applies_once(handler, db, order):
    event = payment_event(order.id)

    first = await handler.handle(event)
    second = await handler.handle(event)

    assert (first, second) == (HandleResult.PROCESSED, HandleResult.DUPLICATE)
    assert len(db.events) == 1


async def test_a_second_distinct_confirmation_is_harmless(handler, db, order):
    await handler.handle(payment_event(order.id))
    await handler.handle(payment_event(order.id))

    assert db.orders[order.id].status is OrderStatus.PAID
    assert [type(e) for e in db.events] == [OrderPaid]


async def test_confirmation_for_a_cancelled_order_keeps_it_cancelled_and_requests_a_refund(
    handler, db, order
):
    await handler.handle(payment_event(order.id, "PaymentExpired"))
    late = payment_event(order.id, "PaymentConfirmed")

    result = await handler.handle(late)

    assert result is HandleResult.REFUND_REQUESTED
    assert db.orders[order.id].status is OrderStatus.CANCELLED
    assert [type(e) for e in db.events] == [OrderCancelled, PaymentRefundRequested]
    refund = db.events[-1]
    assert refund.payment_id == UUID(late.payload["payment_id"])
    assert (refund.amount_cents, refund.currency) == (3980, "BRL")
    ((_, kind, payment_id),) = db.audit
    assert kind == "LATE_PAYMENT" and payment_id == refund.payment_id


async def test_the_same_late_payment_delivered_twice_requests_one_refund(handler, db, order):
    await handler.handle(payment_event(order.id, "PaymentExpired"))
    late = payment_event(order.id, "PaymentConfirmed")
    redelivery = IncomingEvent(uuid4(), late.type, late.key, late.payload)

    await handler.handle(late)
    await handler.handle(late)
    second = await handler.handle(redelivery)

    assert second is HandleResult.REFUND_REQUESTED
    assert [type(e) for e in db.events].count(PaymentRefundRequested) == 1
    assert len(db.audit) == 1


async def test_expiry_for_a_paid_order_is_a_conflict_and_changes_nothing(handler, db, order):
    await handler.handle(payment_event(order.id, "PaymentConfirmed"))

    result = await handler.handle(payment_event(order.id, "PaymentExpired"))

    assert result is HandleResult.CONFLICT
    assert db.orders[order.id].status is OrderStatus.PAID


async def test_event_for_unknown_order_is_ignored(handler, db):
    assert await handler.handle(payment_event(uuid4())) is HandleResult.IGNORED
    assert db.events == [] and db.inbox == set()


async def test_other_event_types_are_ignored(handler, db, order):
    event = IncomingEvent(uuid4(), "PaymentCreated", str(order.id), {"order_id": str(order.id)})

    assert await handler.handle(event) is HandleResult.IGNORED
    assert db.orders[order.id].status is OrderStatus.PENDING and db.inbox == set()


def test_fake_events_are_the_domain_ones():
    assert OrderCreated.__name__ == "OrderCreated"


async def test_stock_rejected_cancels_the_order_as_out_of_stock(handler, db, order):
    result = await handler.handle(payment_event(order.id, "StockRejected"))

    assert result is HandleResult.PROCESSED
    assert db.orders[order.id].status is OrderStatus.CANCELLED
    assert db.orders[order.id].cancel_reason == "out of stock"
    (event,) = db.events
    assert isinstance(event, OrderCancelled) and event.reason == "out of stock"


async def test_stock_rejected_for_an_already_paid_order_is_a_conflict(handler, db, order):
    await handler.handle(payment_event(order.id, "PaymentConfirmed"))

    result = await handler.handle(payment_event(order.id, "StockRejected"))

    assert result is HandleResult.CONFLICT
    assert db.orders[order.id].status is OrderStatus.PAID
