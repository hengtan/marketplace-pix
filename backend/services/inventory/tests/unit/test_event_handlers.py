from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from inventory.application.common import Outcome, ReservationNotFound
from inventory.application.event_handlers import HandleOrderEvent, HandlePaymentEvent
from inventory.application.ports import IncomingEvent
from inventory.domain.reservation import ReservationStatus
from tests.fakes import FakeDatabase, FakeUow

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


@pytest.fixture
def db():
    database = FakeDatabase()
    database.ids = database.seed(a=10)
    return database


@pytest.fixture
def orders(db):
    return HandleOrderEvent(lambda: FakeUow(db), timedelta(minutes=35), lambda: NOW)


@pytest.fixture
def payments(db):
    return HandlePaymentEvent(lambda: FakeUow(db))


def event(event_type, order_id, event_id=None, **extra):
    return IncomingEvent(
        id=event_id or uuid4(),
        type=event_type,
        key=str(order_id),
        payload={"order_id": str(order_id), **extra},
    )


def order_created(db, order_id, quantity=2, event_id=None):
    items = [
        {
            "product_id": str(db.ids["a"]),
            "merchant_id": str(uuid4()),
            "quantity": quantity,
            "unit_price_cents": 1000,
        }
    ]
    return event("OrderCreated", order_id, event_id, items=items, total_cents=2000, currency="BRL")


async def test_order_created_reserves_stock(orders, db):
    order_id = uuid4()

    assert await orders.handle(order_created(db, order_id)) is Outcome.PROCESSED

    assert db.reservations[order_id].status is ReservationStatus.RESERVED
    assert (db.stocks[db.ids["a"]].available, db.stocks[db.ids["a"]].reserved) == (8, 2)


async def test_duplicated_order_created_is_deduplicated_by_the_inbox(orders, db):
    order_id, event_id = uuid4(), uuid4()

    first = await orders.handle(order_created(db, order_id, event_id=event_id))
    second = await orders.handle(order_created(db, order_id, event_id=event_id))

    assert (first, second) == (Outcome.PROCESSED, Outcome.DUPLICATE)
    assert db.stocks[db.ids["a"]].reserved == 2
    assert db.event_types() == ["StockReserved"]


async def test_order_created_with_malformed_items_is_skipped(orders, db):
    bad = event("OrderCreated", uuid4(), items="nope")

    assert await orders.handle(bad) is Outcome.IGNORED
    assert db.reservations == {}


async def test_order_cancelled_releases_the_reservation(orders, db):
    order_id = uuid4()
    await orders.handle(order_created(db, order_id))

    outcome = await orders.handle(event("OrderCancelled", order_id, reason="payment expired"))

    assert outcome is Outcome.PROCESSED
    assert db.stocks[db.ids["a"]].available == 10
    assert db.events[-1].reason == "order_cancelled"


async def test_unrelated_event_types_are_ignored(orders, payments, db):
    assert await orders.handle(event("OrderPaid", uuid4())) is Outcome.IGNORED
    assert await payments.handle(event("PaymentCreated", uuid4())) is Outcome.IGNORED
    assert db.inbox == set()


async def test_payment_confirmed_commits_the_sale(orders, payments, db):
    order_id = uuid4()
    await orders.handle(order_created(db, order_id))

    outcome = await payments.handle(event("PaymentConfirmed", order_id))

    assert outcome is Outcome.PROCESSED
    assert (db.stocks[db.ids["a"]].available, db.stocks[db.ids["a"]].reserved) == (8, 0)
    assert db.event_types() == ["StockReserved", "StockCommitted"]


async def test_payment_confirmed_before_order_created_fails_then_works_on_retry(
    orders, payments, db
):
    order_id = uuid4()
    confirmed = event("PaymentConfirmed", order_id)

    with pytest.raises(ReservationNotFound):
        await payments.handle(confirmed)
    await orders.handle(order_created(db, order_id))
    outcome = await payments.handle(confirmed)

    assert outcome is Outcome.PROCESSED
    assert db.reservations[order_id].status is ReservationStatus.COMMITTED


@pytest.mark.parametrize(
    ("event_type", "reason"),
    [("PaymentExpired", "payment_expired"), ("PaymentCancelled", "payment_cancelled")],
)
async def test_payment_expired_and_cancelled_release_the_reservation(
    orders, payments, db, event_type, reason
):
    order_id = uuid4()
    await orders.handle(order_created(db, order_id))

    outcome = await payments.handle(event(event_type, order_id))

    assert outcome is Outcome.PROCESSED
    assert db.stocks[db.ids["a"]].available == 10
    assert db.events[-1].reason == reason


async def test_release_events_arriving_twice_release_once(orders, payments, db):
    order_id = uuid4()
    await orders.handle(order_created(db, order_id))

    await payments.handle(event("PaymentExpired", order_id))
    await payments.handle(event("PaymentCancelled", order_id))
    await orders.handle(event("OrderCancelled", order_id))

    assert db.stocks[db.ids["a"]].available == 10
    assert db.event_types().count("StockReleased") == 1
