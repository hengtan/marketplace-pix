from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from inventory.domain.errors import InvalidReservation, InvalidStateTransition
from inventory.domain.events import StockCommitted, StockRejected, StockReleased, StockReserved
from inventory.domain.reservation import Reservation, ReservationItem, ReservationStatus
from inventory.domain.stock import Stock

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
TTL = timedelta(minutes=35)


def place(items, stocks):
    return Reservation.place(uuid4(), items, stocks, NOW, TTL)


def test_place_reserves_every_item_and_sets_ttl():
    a, b = uuid4(), uuid4()
    stocks = {a: Stock(a, 5), b: Stock(b, 5)}

    reservation = place([ReservationItem(a, 2), ReservationItem(b, 5)], stocks)

    assert reservation.status is ReservationStatus.RESERVED
    assert reservation.expires_at == NOW + TTL
    assert (stocks[a].available, stocks[a].reserved) == (3, 2)
    assert (stocks[b].available, stocks[b].reserved) == (0, 5)
    assert [type(e) for e in reservation.pull_events()] == [StockReserved]


def test_place_is_all_or_nothing_and_reports_every_shortage():
    a, b, unknown = uuid4(), uuid4(), uuid4()
    stocks = {a: Stock(a, 5), b: Stock(b, 1)}

    reservation = place(
        [ReservationItem(a, 2), ReservationItem(b, 3), ReservationItem(unknown, 1)], stocks
    )

    assert reservation.status is ReservationStatus.REJECTED
    assert (stocks[a].available, stocks[a].reserved) == (5, 0)
    assert (stocks[b].available, stocks[b].reserved) == (1, 0)
    (event,) = reservation.pull_events()
    assert isinstance(event, StockRejected)
    assert {(m.product_id, m.requested, m.available) for m in event.missing} == {
        (b, 3, 1),
        (unknown, 1, 0),
    }


def test_repeated_product_lines_are_summed_before_checking():
    a = uuid4()
    stocks = {a: Stock(a, 3)}

    reservation = place([ReservationItem(a, 2), ReservationItem(a, 2)], stocks)

    assert reservation.status is ReservationStatus.REJECTED
    assert stocks[a].available == 3


def test_place_requires_items_and_positive_quantities():
    with pytest.raises(InvalidReservation):
        place([], {})
    with pytest.raises(InvalidReservation):
        ReservationItem(uuid4(), 0)


def test_commit_sells_reserved_units():
    a = uuid4()
    stocks = {a: Stock(a, 5)}
    reservation = place([ReservationItem(a, 2)], stocks)
    reservation.pull_events()

    reservation.commit(stocks)

    assert reservation.status is ReservationStatus.COMMITTED
    assert (stocks[a].available, stocks[a].reserved) == (3, 0)
    assert [type(e) for e in reservation.pull_events()] == [StockCommitted]


def test_release_returns_units_and_carries_the_reason():
    a = uuid4()
    stocks = {a: Stock(a, 5)}
    reservation = place([ReservationItem(a, 2)], stocks)
    reservation.pull_events()

    reservation.release(stocks, "payment_expired")

    assert reservation.status is ReservationStatus.RELEASED
    assert (stocks[a].available, stocks[a].reserved) == (5, 0)
    (event,) = reservation.pull_events()
    assert isinstance(event, StockReleased)
    assert event.reason == "payment_expired"


@pytest.mark.parametrize("action", ["commit", "release"])
def test_only_reserved_reservations_can_change_state(action):
    a = uuid4()
    stocks = {a: Stock(a, 5)}
    reservation = place([ReservationItem(a, 2)], stocks)
    reservation.release(stocks, "x")

    with pytest.raises(InvalidStateTransition):
        if action == "commit":
            reservation.commit(stocks)
        else:
            reservation.release(stocks, "again")

    assert (stocks[a].available, stocks[a].reserved) == (5, 0)


def test_is_expired_only_for_reserved_past_ttl():
    a = uuid4()
    stocks = {a: Stock(a, 5)}
    reservation = place([ReservationItem(a, 1)], stocks)

    assert not reservation.is_expired(NOW + TTL - timedelta(seconds=1))
    assert reservation.is_expired(NOW + TTL)
    reservation.release(stocks, "x")
    assert not reservation.is_expired(NOW + TTL)
