from uuid import uuid4

import pytest

from ordering.domain.errors import InvalidOrder, InvalidStateTransition
from ordering.domain.events import OrderCancelled, OrderCreated, OrderPaid
from ordering.domain.money import Money
from ordering.domain.order import Order, OrderItem, OrderStatus


def item(qty=1, price=1990, currency="BRL") -> OrderItem:
    return OrderItem(uuid4(), uuid4(), qty, Money(price, currency))


def make_order(items=None) -> Order:
    items = items or [item(2, 1990), item(1, 500)]
    return Order.create(uuid4(), items, "Maria Souza", "maria@example.com")


def test_create_computes_total_and_emits_event_with_items_and_contact():
    order = make_order()
    assert order.status is OrderStatus.PENDING
    assert order.total == Money(4480)
    (event,) = order.pull_events()
    assert isinstance(event, OrderCreated)
    assert event.total_cents == 4480
    assert event.customer_name == "Maria Souza"
    assert event.customer_email == "maria@example.com"
    assert [(i.quantity, i.unit_price_cents) for i in event.items] == [(2, 1990), (1, 500)]
    assert event.items[0].merchant_id == order.items[0].merchant_id


def test_pull_events_clears_the_buffer():
    order = make_order()
    order.pull_events()
    assert order.pull_events() == []


def test_empty_order_is_rejected():
    with pytest.raises(InvalidOrder):
        Order.create(uuid4(), [], "Maria", "maria@example.com")


def test_blank_name_and_invalid_email_are_rejected():
    with pytest.raises(InvalidOrder):
        Order.create(uuid4(), [item()], "   ", "maria@example.com")
    with pytest.raises(InvalidOrder):
        Order.create(uuid4(), [item()], "Maria", "not-an-email")


def test_zero_quantity_is_rejected():
    with pytest.raises(InvalidOrder):
        item(qty=0)


def test_mixed_currency_is_rejected():
    with pytest.raises(InvalidOrder):
        make_order([item(currency="BRL"), item(currency="USD")])


def test_mark_paid_is_idempotent():
    order = make_order()
    order.pull_events()
    order.mark_paid()
    order.mark_paid()
    events = order.pull_events()
    assert order.status is OrderStatus.PAID
    assert [type(e) for e in events] == [OrderPaid]


def test_cancel_pending_order_records_the_reason():
    order = make_order()
    order.pull_events()
    order.cancel("pix expired")
    events = order.pull_events()
    assert order.status is OrderStatus.CANCELLED
    assert order.cancel_reason == "pix expired"
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
