from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ledger.domain.errors import InvalidMoney
from ledger.domain.money import Money
from ledger.domain.split import platform_fee, split_order


@pytest.mark.parametrize(
    ("subtotal", "fee"),
    [
        (0, 0),
        (1, 0),
        (4, 0),
        (5, 1),
        (6, 1),
        (14, 1),
        (15, 2),
        (100, 10),
        (3333, 333),
        (3335, 334),
        (34990, 3499),
        (21995, 2200),
        (999_999_999, 100_000_000),
    ],
)
def test_fee_is_ten_percent_rounded_half_up(subtotal, fee):
    assert platform_fee(Money(subtotal)).cents == fee


def test_fee_rate_must_be_valid():
    with pytest.raises(InvalidMoney):
        platform_fee(Money(100), fee_bps=10_001)
    with pytest.raises(InvalidMoney):
        platform_fee(Money(100), fee_bps=-1)


def test_merchant_receives_the_remainder_so_totals_close():
    merchants = [uuid4() for _ in range(3)]
    subtotals = {merchants[0]: Money(10005), merchants[1]: Money(1), merchants[2]: Money(999)}

    splits = split_order(subtotals)

    for split in splits:
        assert split.fee + split.net == split.gross
    assert sum(s.gross.cents for s in splits) == 11005
    assert sum(s.fee.cents + s.net.cents for s in splits) == 11005


def test_one_cent_order_goes_entirely_to_the_merchant():
    merchant = uuid4()
    (split,) = split_order({merchant: Money(1)})
    assert split.fee.cents == 0
    assert split.net.cents == 1


def test_split_order_is_deterministic():
    subtotals = {uuid4(): Money(i * 7 + 1) for i in range(6)}
    assert split_order(subtotals) == split_order(dict(reversed(subtotals.items())))


@given(
    st.lists(st.integers(min_value=1, max_value=10**9), min_size=1, max_size=12),
    st.integers(min_value=0, max_value=10_000),
)
def test_split_always_closes_for_any_subtotals_and_rate(cents, bps):
    subtotals = {uuid4(): Money(c) for c in cents}

    splits = split_order(subtotals, bps)

    for split in splits:
        assert split.fee.cents + split.net.cents == split.gross.cents
        assert 0 <= split.fee.cents <= split.gross.cents
    assert sum(s.fee.cents + s.net.cents for s in splits) == sum(cents)
