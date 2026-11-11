from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ordering.application.saga_timeout import SagaTimeoutManager
from ordering.domain.events import OrderCancelled
from ordering.domain.money import Money
from ordering.domain.order import Order, OrderItem, OrderStatus
from tests.fakes import FakeDatabase, FakeUow

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
TIMEOUT = timedelta(minutes=45)


@pytest.fixture
def db() -> FakeDatabase:
    return FakeDatabase()


@pytest.fixture
def manager(db: FakeDatabase) -> SagaTimeoutManager:
    return SagaTimeoutManager(lambda: FakeUow(db), TIMEOUT, batch_size=10, clock=lambda: NOW)


def place(db: FakeDatabase, age: timedelta, status: OrderStatus = OrderStatus.PENDING) -> Order:
    order = Order.create(
        uuid4(), [OrderItem(uuid4(), uuid4(), 1, Money(1000))], "Maria", "maria@example.com"
    )
    order.pull_events()
    order.status = status
    order.created_at = NOW - age
    db.orders[order.id] = order
    return order


async def test_an_order_stuck_past_the_deadline_is_cancelled_with_compensation_event(db, manager):
    stuck = place(db, timedelta(minutes=46))

    assert await manager.run_once() == 1

    assert db.orders[stuck.id].status is OrderStatus.CANCELLED
    assert db.orders[stuck.id].cancel_reason == "saga timeout"
    (event,) = db.events
    assert isinstance(event, OrderCancelled) and event.reason == "saga timeout"
    ((order_id, kind, _),) = db.audit
    assert (order_id, kind) == (stuck.id, "SAGA_TIMEOUT")


async def test_orders_inside_the_deadline_or_already_settled_are_left_alone(db, manager):
    fresh = place(db, timedelta(minutes=10))
    paid = place(db, timedelta(hours=3), OrderStatus.PAID)
    cancelled = place(db, timedelta(hours=3), OrderStatus.CANCELLED)

    assert await manager.run_once() == 0

    assert db.orders[fresh.id].status is OrderStatus.PENDING
    assert db.orders[paid.id].status is OrderStatus.PAID
    assert db.orders[cancelled.id].status is OrderStatus.CANCELLED
    assert db.events == []


async def test_running_the_sweep_again_does_not_emit_a_second_event(db, manager):
    place(db, timedelta(hours=2))

    assert await manager.run_once() == 1
    assert await manager.run_once() == 0
    assert await manager.run_once() == 0

    assert [type(e) for e in db.events] == [OrderCancelled]


async def test_a_sweep_handles_at_most_one_batch(db):
    for _ in range(5):
        place(db, timedelta(hours=2))
    manager = SagaTimeoutManager(lambda: FakeUow(db), TIMEOUT, batch_size=2, clock=lambda: NOW)

    assert [await manager.run_once() for _ in range(4)] == [2, 2, 1, 0]
