import pytest

from ordering.domain.errors import InvalidMoney
from ordering.domain.money import Money


def test_add_same_currency():
    assert Money(150) + Money(250) == Money(400)


def test_times_quantity():
    assert Money(1990).times(3) == Money(5970)


def test_negative_is_rejected():
    with pytest.raises(InvalidMoney):
        Money(-1)


def test_float_is_rejected():
    with pytest.raises(InvalidMoney):
        Money(19.9)  # type: ignore[arg-type]


def test_currency_mismatch_is_rejected():
    with pytest.raises(InvalidMoney):
        Money(100, "BRL") + Money(100, "USD")
