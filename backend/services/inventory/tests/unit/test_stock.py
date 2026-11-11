from uuid import uuid4

import pytest

from inventory.domain.errors import InsufficientStock, InvalidQuantity
from inventory.domain.stock import Stock


def make(available=10, reserved=0) -> Stock:
    return Stock(uuid4(), available, reserved)


def test_reserve_moves_units_from_available_to_reserved():
    stock = make(10)

    stock.reserve(3)

    assert (stock.available, stock.reserved) == (7, 3)


def test_reserve_more_than_available_fails_and_changes_nothing():
    stock = make(2)

    with pytest.raises(InsufficientStock):
        stock.reserve(3)

    assert (stock.available, stock.reserved) == (2, 0)


def test_release_returns_units_to_available():
    stock = make(7, 3)

    stock.release(3)

    assert (stock.available, stock.reserved) == (10, 0)


def test_sell_removes_units_from_reserved_only():
    stock = make(7, 3)

    stock.sell(2)

    assert (stock.available, stock.reserved) == (7, 1)


def test_cannot_release_or_sell_more_than_reserved():
    stock = make(5, 1)

    with pytest.raises(InvalidQuantity):
        stock.release(2)
    with pytest.raises(InvalidQuantity):
        stock.sell(2)


@pytest.mark.parametrize("quantity", [0, -1])
def test_quantities_must_be_positive(quantity):
    stock = make(5, 5)

    for action in (stock.reserve, stock.release, stock.sell):
        with pytest.raises(InvalidQuantity):
            action(quantity)


def test_set_available_keeps_reserved_and_rejects_negative():
    stock = make(5, 2)

    stock.set_available(20)

    assert (stock.available, stock.reserved) == (20, 2)
    with pytest.raises(InvalidQuantity):
        stock.set_available(-1)


def test_negative_stock_cannot_be_built():
    with pytest.raises(InvalidQuantity):
        Stock(uuid4(), -1, 0)
