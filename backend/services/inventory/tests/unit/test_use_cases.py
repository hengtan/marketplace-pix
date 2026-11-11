from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from inventory.application.commit_stock import CommitStock
from inventory.application.common import Delivery, Outcome, ReservationNotFound
from inventory.application.expire_reservations import ExpireReservations
from inventory.application.release_stock import ReleaseStock
from inventory.application.reserve_stock import ReserveStock
from inventory.application.stock_queries import GetStock, SetStock
from inventory.domain.errors import InvalidQuantity
from inventory.domain.events import StockRejected
from inventory.domain.reservation import ReservationItem, ReservationStatus
from tests.fakes import FakeDatabase, FakeUow

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
TTL = timedelta(minutes=35)


@pytest.fixture
def db():
    database = FakeDatabase()
    database.ids = database.seed(a=10, b=3)
    return database


def uow_factory(db):
    return lambda: FakeUow(db)


def reserve_use_case(db, now=NOW):
    return ReserveStock(uow_factory(db), TTL, lambda: now)


def levels(db, name):
    stock = db.stocks[db.ids[name]]
    return stock.available, stock.reserved


async def place(db, items, order_id=None, now=NOW, delivery=None):
    order_id = order_id or uuid4()
    outcome = await reserve_use_case(db, now).execute(
        order_id, [ReservationItem(db.ids[n], q) for n, q in items], delivery
    )
    return order_id, outcome


async def test_reservation_moves_stock_and_publishes_stock_reserved(db):
    order_id, outcome = await place(db, [("a", 4), ("b", 1)])

    assert outcome is Outcome.PROCESSED
    assert levels(db, "a") == (6, 4)
    assert levels(db, "b") == (2, 1)
    reservation = db.reservations[order_id]
    assert reservation.status is ReservationStatus.RESERVED
    assert reservation.expires_at == NOW + TTL
    assert db.event_types() == ["StockReserved"]


async def test_insufficient_stock_rejects_everything_without_touching_stock(db):
    order_id, _ = await place(db, [("a", 4), ("b", 4)])

    assert db.reservations[order_id].status is ReservationStatus.REJECTED
    assert levels(db, "a") == (10, 0)
    assert levels(db, "b") == (3, 0)
    (event,) = db.events
    assert isinstance(event, StockRejected)
    assert [(m.requested, m.available) for m in event.missing] == [(4, 3)]


async def test_reservation_is_idempotent_per_order(db):
    order_id, first = await place(db, [("a", 4)])
    _, second = await place(db, [("a", 4)], order_id=order_id)

    assert (first, second) == (Outcome.PROCESSED, Outcome.DUPLICATE)
    assert levels(db, "a") == (6, 4)
    assert db.event_types() == ["StockReserved"]


async def test_same_event_delivered_twice_is_processed_once(db):
    delivery = Delivery(uuid4(), "inventory-orders")
    order_id = uuid4()

    first = await place(db, [("a", 1)], order_id, delivery=delivery)
    second = await place(db, [("a", 1)], order_id, delivery=delivery)

    assert (first[1], second[1]) == (Outcome.PROCESSED, Outcome.DUPLICATE)
    assert levels(db, "a") == (9, 1)


async def test_commit_sells_reserved_units_and_publishes_stock_committed(db):
    order_id, _ = await place(db, [("a", 4)])

    outcome = await CommitStock(uow_factory(db)).execute(order_id)

    assert outcome is Outcome.PROCESSED
    assert levels(db, "a") == (6, 0)
    assert db.reservations[order_id].status is ReservationStatus.COMMITTED
    assert db.event_types() == ["StockReserved", "StockCommitted"]


async def test_commit_before_the_reservation_exists_raises_and_leaves_no_trace(db):
    order_id = uuid4()
    delivery = Delivery(uuid4(), "inventory-payments")

    with pytest.raises(ReservationNotFound):
        await CommitStock(uow_factory(db)).execute(order_id, delivery)

    assert db.inbox == set()
    await place(db, [("a", 2)], order_id)
    outcome = await CommitStock(uow_factory(db)).execute(order_id, delivery)
    assert outcome is Outcome.PROCESSED
    assert levels(db, "a") == (8, 0)


async def test_commit_of_a_rejected_reservation_is_ignored_with_an_alert(db, caplog):
    order_id, _ = await place(db, [("b", 9)])

    outcome = await CommitStock(uow_factory(db)).execute(order_id)

    assert outcome is Outcome.IGNORED
    assert "refund required" in caplog.text
    assert db.reservations[order_id].status is ReservationStatus.REJECTED
    assert db.event_types() == ["StockRejected"]


async def test_commit_twice_does_not_sell_twice(db):
    order_id, _ = await place(db, [("a", 4)])
    commit = CommitStock(uow_factory(db))

    await commit.execute(order_id)
    second = await commit.execute(order_id)

    assert second is Outcome.IGNORED
    assert levels(db, "a") == (6, 0)
    assert db.event_types().count("StockCommitted") == 1


async def test_release_returns_units_and_publishes_stock_released(db):
    order_id, _ = await place(db, [("a", 4)])

    outcome = await ReleaseStock(uow_factory(db)).execute(order_id, "payment_expired")

    assert outcome is Outcome.PROCESSED
    assert levels(db, "a") == (10, 0)
    assert db.reservations[order_id].status is ReservationStatus.RELEASED
    assert db.events[-1].reason == "payment_expired"


async def test_releasing_twice_does_not_duplicate_units_or_events(db):
    order_id, _ = await place(db, [("a", 4)])
    release = ReleaseStock(uow_factory(db))

    await release.execute(order_id, "payment_expired")
    second = await release.execute(order_id, "order_cancelled")

    assert second is Outcome.IGNORED
    assert levels(db, "a") == (10, 0)
    assert db.event_types().count("StockReleased") == 1


async def test_release_ignores_committed_rejected_and_unknown_orders(db):
    committed, _ = await place(db, [("a", 1)])
    await CommitStock(uow_factory(db)).execute(committed)
    rejected, _ = await place(db, [("b", 9)])
    release = ReleaseStock(uow_factory(db))

    results = [await release.execute(o, "order_cancelled") for o in (committed, rejected, uuid4())]

    assert results == [Outcome.IGNORED] * 3
    assert levels(db, "a") == (9, 0)
    assert "StockReleased" not in db.event_types()


async def test_expiry_job_releases_only_reservations_past_their_ttl(db):
    old, _ = await place(db, [("a", 4)], now=NOW)
    fresh, _ = await place(db, [("b", 1)], now=NOW + timedelta(minutes=30))
    job = ExpireReservations(uow_factory(db), clock=lambda: NOW + TTL)

    assert await job.run_once() == 1
    assert await job.run_once() == 0

    assert db.reservations[old].status is ReservationStatus.RELEASED
    assert db.reservations[fresh].status is ReservationStatus.RESERVED
    assert levels(db, "a") == (10, 0)
    assert levels(db, "b") == (2, 1)
    assert db.events[-1].reason == "reservation_expired"


async def test_expiry_job_does_not_touch_committed_reservations(db):
    order_id, _ = await place(db, [("a", 4)])
    await CommitStock(uow_factory(db)).execute(order_id)

    assert await ExpireReservations(uow_factory(db), clock=lambda: NOW + TTL * 2).run_once() == 0
    assert levels(db, "a") == (6, 0)


async def test_get_stock_returns_zeros_for_unknown_products_in_the_requested_order(db):
    unknown = uuid4()

    result = await GetStock(uow_factory(db)).execute([unknown, db.ids["a"]])

    assert [(s.product_id, s.available, s.reserved) for s in result] == [
        (unknown, 0, 0),
        (db.ids["a"], 10, 0),
    ]


async def test_set_stock_overwrites_available_and_keeps_reserved(db):
    await place(db, [("a", 4)])

    stock = await SetStock(uow_factory(db)).execute(db.ids["a"], 50)

    assert (stock.available, stock.reserved) == (50, 4)
    assert levels(db, "a") == (50, 4)


async def test_set_stock_creates_unknown_products_and_rejects_negative(db):
    new_id = uuid4()

    await SetStock(uow_factory(db)).execute(new_id, 7)

    assert db.stocks[new_id].available == 7
    with pytest.raises(InvalidQuantity):
        await SetStock(uow_factory(db)).execute(new_id, -1)
