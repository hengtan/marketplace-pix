from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ledger.domain.account import Account, Direction
from ledger.domain.errors import InvalidMoney, InvalidTransaction, UnbalancedTransaction
from ledger.domain.money import Money
from ledger.domain.transaction import Entry, Transaction

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def entry(account, direction, cents, currency="BRL"):
    return Entry(account, direction, Money(cents, currency), "test")


def post(entries):
    return Transaction.post(
        order_id=uuid4(),
        payment_id=uuid4(),
        entries=entries,
        created_at=NOW,
        platform_fee=Money.zero(),
    )


def test_balanced_transaction_is_accepted_and_emits_event():
    merchant = Account.merchant(uuid4())
    tx = post(
        [
            entry(Account.psp_receivable(), Direction.DEBIT, 1000),
            entry(merchant, Direction.CREDIT, 900),
            entry(Account.platform_revenue(), Direction.CREDIT, 100),
        ]
    )

    assert tx.total_debits == tx.total_credits == Money(1000)
    (event,) = tx.pull_events()
    assert event.total_cents == 1000
    assert tx.pull_events() == []


def test_unbalanced_transaction_is_rejected():
    with pytest.raises(UnbalancedTransaction):
        post(
            [
                entry(Account.psp_receivable(), Direction.DEBIT, 1000),
                entry(Account.merchant(uuid4()), Direction.CREDIT, 999),
            ]
        )


def test_transaction_with_a_single_entry_is_rejected():
    with pytest.raises(InvalidTransaction):
        post([entry(Account.psp_receivable(), Direction.DEBIT, 1)])
    with pytest.raises(InvalidTransaction):
        post([])


def test_zero_or_negative_entries_are_rejected():
    with pytest.raises(InvalidTransaction):
        entry(Account.psp_receivable(), Direction.DEBIT, 0)
    with pytest.raises(InvalidMoney):
        entry(Account.psp_receivable(), Direction.DEBIT, -5)


def test_mixed_currencies_are_rejected():
    with pytest.raises(InvalidTransaction):
        post(
            [
                entry(Account.psp_receivable(), Direction.DEBIT, 1000),
                entry(Account.merchant(uuid4()), Direction.CREDIT, 1000, currency="USD"),
            ]
        )


def test_balance_deltas_follow_each_accounts_normal_side():
    merchant = Account.merchant(uuid4())
    tx = post(
        [
            entry(Account.psp_receivable(), Direction.DEBIT, 1000),
            entry(merchant, Direction.CREDIT, 900),
            entry(Account.platform_revenue(), Direction.CREDIT, 100),
        ]
    )

    deltas = {a.id: d for a, d in tx.balance_deltas().items()}

    assert deltas == {"psp:receivable": 1000, merchant.id: 900, "platform:revenue": 100}
    assert list(deltas) == sorted(deltas)
