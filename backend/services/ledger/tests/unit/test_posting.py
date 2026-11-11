from datetime import UTC, datetime
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ledger.domain.account import Account, Direction
from ledger.domain.errors import InvalidOrderProjection, PaymentMismatch
from ledger.domain.money import Money
from ledger.domain.order_projection import OrderProjection, ProjectedItem
from ledger.domain.posting import build_payment_transaction

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def projection(*lines):
    items = tuple(
        ProjectedItem(uuid4(), merchant, qty, Money(price)) for merchant, qty, price in lines
    )
    return OrderProjection(uuid4(), "BRL", items, NOW)


def credits_by_account(tx):
    result: dict[str, int] = {}
    for e in tx.entries:
        if e.direction is Direction.CREDIT:
            result[e.account.id] = result.get(e.account.id, 0) + e.amount.cents
    return result


def test_projection_computes_subtotals_per_merchant():
    a, b = uuid4(), uuid4()
    p = projection((a, 2, 1000), (b, 1, 500), (a, 1, 250))

    assert p.merchant_subtotals() == {a: Money(2250), b: Money(500)}
    assert p.total == Money(2750)


def test_projection_requires_items():
    with pytest.raises(InvalidOrderProjection):
        OrderProjection(uuid4(), "BRL", (), NOW)


def test_single_merchant_split_is_ninety_ten():
    merchant = uuid4()
    p = projection((merchant, 1, 34990))

    tx = build_payment_transaction(p, uuid4(), p.total, NOW)

    assert tx.total_debits == tx.total_credits == Money(34990)
    assert credits_by_account(tx) == {f"merchant:{merchant}": 31491, "platform:revenue": 3499}
    assert tx.platform_fee == Money(3499)
    assert [e.account.id for e in tx.entries if e.direction is Direction.DEBIT] == [
        "psp:receivable"
    ]


def test_odd_amounts_and_several_merchants_always_close():
    a, b, c = uuid4(), uuid4(), uuid4()
    p = projection((a, 3, 3335), (b, 1, 1), (c, 7, 19999))

    tx = build_payment_transaction(p, uuid4(), p.total, NOW)

    assert tx.total_debits == tx.total_credits == p.total
    credited = credits_by_account(tx)
    assert credited[f"merchant:{b}"] == 1
    assert sum(credited.values()) == p.total.cents


def test_one_cent_order_creates_no_zero_fee_entry():
    merchant = uuid4()
    p = projection((merchant, 1, 1))

    tx = build_payment_transaction(p, uuid4(), p.total, NOW)

    assert [e.amount.cents for e in tx.entries] == [1, 1]
    assert tx.platform_fee == Money.zero()


def test_payment_amount_must_match_order_total():
    p = projection((uuid4(), 1, 1000))
    with pytest.raises(PaymentMismatch):
        build_payment_transaction(p, uuid4(), Money(999), NOW)
    with pytest.raises(PaymentMismatch):
        build_payment_transaction(p, uuid4(), Money(1000, "USD"), NOW)


@given(
    st.lists(
        st.tuples(
            st.integers(min_value=0, max_value=4),
            st.integers(min_value=1, max_value=20),
            st.integers(min_value=1, max_value=5_000_000),
        ),
        min_size=1,
        max_size=15,
    ),
    st.integers(min_value=0, max_value=10_000),
)
def test_property_debits_equal_credits_and_balances_add_up_to_the_total(lines, bps):
    merchants = [uuid4() for _ in range(5)]
    p = projection(*[(merchants[m], qty, price) for m, qty, price in lines])

    tx = build_payment_transaction(p, uuid4(), p.total, NOW, fee_bps=bps)

    assert tx.total_debits == tx.total_credits == p.total
    deltas = {a.id: d for a, d in tx.balance_deltas().items()}
    merchant_total = sum(v for k, v in deltas.items() if k.startswith("merchant:"))
    assert merchant_total + deltas.get("platform:revenue", 0) == p.total.cents
    assert deltas["psp:receivable"] == p.total.cents
    assert Account.psp_receivable().id in deltas
