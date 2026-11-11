from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from marketplace_common.messaging import IncomingEvent

from inventory.application.common import Outcome
from inventory.application.event_handlers import HandleOrderEvent, HandlePaymentEvent
from inventory.domain.reservation import ReservationStatus
from tests.fakes import FakeDatabase, FakeUow

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def event(event_type, order_id, **extra):
    return IncomingEvent(
        id=uuid4(),
        type=event_type,
        key=str(order_id),
        payload={"order_id": str(order_id), **extra},
    )


@pytest.fixture
def db():
    database = FakeDatabase()
    database.ids = database.seed(a=10)
    return database


@pytest.fixture
def handlers(db):
    return (
        HandleOrderEvent(lambda: FakeUow(db), timedelta(minutes=35), lambda: NOW),
        HandlePaymentEvent(lambda: FakeUow(db)),
    )


async def sold_order(db, orders, payments, quantity=3):
    order_id = uuid4()
    items = [{"product_id": str(db.ids["a"]), "quantity": quantity}]
    await orders.handle(event("OrderCreated", order_id, items=items))
    await payments.handle(event("PaymentConfirmed", order_id))
    return order_id


async def test_a_refund_puts_sold_units_back_on_the_shelf(db, handlers):
    orders, payments = handlers
    order_id = await sold_order(db, orders, payments)
    assert (db.stocks[db.ids["a"]].available, db.stocks[db.ids["a"]].reserved) == (7, 0)

    result = await payments.handle(event("PaymentRefunded", order_id))

    assert result is Outcome.PROCESSED
    assert db.stocks[db.ids["a"]].available == 10
    assert db.reservations[order_id].status is ReservationStatus.RELEASED
    assert db.event_types()[-1] == "StockReleased"


async def test_the_refund_restock_is_idempotent(db, handlers):
    orders, payments = handlers
    order_id = await sold_order(db, orders, payments)
    refund = event("PaymentRefunded", order_id)

    await payments.handle(refund)
    again = await payments.handle(refund)
    other = await payments.handle(event("PaymentRefunded", order_id))

    assert (again, other) == (Outcome.DUPLICATE, Outcome.IGNORED)
    assert db.stocks[db.ids["a"]].available == 10


async def test_a_refund_without_a_committed_sale_changes_nothing(db, handlers):
    orders, payments = handlers
    order_id = uuid4()
    items = [{"product_id": str(db.ids["a"]), "quantity": 2}]
    await orders.handle(event("OrderCreated", order_id, items=items))
    await orders.handle(event("OrderCancelled", order_id, reason="saga timeout"))
    assert db.stocks[db.ids["a"]].available == 10

    result = await payments.handle(event("PaymentRefunded", order_id))

    assert result is Outcome.IGNORED
    assert db.stocks[db.ids["a"]].available == 10


async def test_cancelling_a_committed_order_does_not_restock_until_the_refund(db, handlers):
    orders, payments = handlers
    order_id = await sold_order(db, orders, payments)

    assert await orders.handle(event("OrderCancelled", order_id, reason="x")) is Outcome.IGNORED
    assert db.stocks[db.ids["a"]].available == 7
