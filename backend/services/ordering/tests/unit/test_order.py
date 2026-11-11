from uuid import uuid4

import pytest

from ordering.domain.errors import InvalidOrder, InvalidStateTransition
from ordering.domain.events import OrderCancelled, OrderCreated, OrderPaid
from ordering.domain.money import Money
from ordering.domain.order import Order, OrderItem, OrderStatus


def make_order() -> Order:
    items = [
        OrderItem(uuid4(), 2, Money(1990)),
        OrderItem(uuid4(), 1, Money(500)),
    ]
    return Order.create(uuid4(), items)


def test_create_computes_total_and_emits_event():
    order = make_order()
    assert order.status is OrderStatus.PENDING
    assert order.total == Money(4480)
    events = order.pull_events()
    assert len(events) == 1
    assert isinstance(events[0], OrderCreated)
    assert events[0].total_cents == 4480


def test_pull_events_clears_the_buffer():
    order = make_order()
    order.pull_events()
    assert order.pull_events() == []


def test_empty_order_is_rejected():
    with pytest.raises(InvalidOrder):
        Order.create(uuid4(), [])


def test_zero_quantity_is_rejected():
    with pytest.raises(InvalidOrder):
        OrderItem(uuid4(), 0, Money(100))


def test_mixed_currency_is_rejected():
    items = [OrderItem(uuid4(), 1, Money(100, "BRL")), OrderItem(uuid4(), 1, Money(100, "USD"))]
    with pytest.raises(InvalidOrder):
        Order.create(uuid4(), items)


def test_mark_paid_is_idempotent():
    order = make_order()
    order.pull_events()
    order.mark_paid()
    order.mark_paid()
    events = order.pull_events()
    assert order.status is OrderStatus.PAID
    assert [type(e) for e in events] == [OrderPaid]


def test_cancel_pending_order():
    order = make_order()
    order.pull_events()
    order.cancel("pix expired")
    events = order.pull_events()
    assert order.status is OrderStatus.CANCELLED
    assert isinstance(events[0], OrderCancelled)
    assert events[0].reason == "pix expired"


def test_cannot_cancel_a_paid_order():
    order = make_order()
    order.mark_paid()
    with pytest.raises(InvalidStateTransition):
        order.cancel("changed my mind")


def test_cannot_pay_a_cancelled_order():
    order = make_order()
    order.cancel("x")
    with pytest.raises(InvalidStateTransition):
        order.mark_paid()
