from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ledger.application.errors import OrderProjectionNotFound
from ledger.application.handle_order_event import HandleOrderEvent
from ledger.application.handle_payment_event import HandlePaymentEvent
from ledger.application.queries import GetMerchantSummary
from ledger.application.results import HandleResult
from ledger.domain.events import LedgerTransactionPosted, LedgerTransactionReversed
from ledger.domain.money import Money
from ledger.domain.order_projection import OrderProjection, ProjectedItem
from ledger.domain.posting import build_payment_transaction, build_reversal_transaction
from ledger.domain.transaction import TransactionKind
from tests.builders import order_created, payment_confirmed, payment_refunded
from tests.fakes import FakeDatabase, FakeUow

NOW = datetime(2026, 11, 11, 15, 30, tzinfo=UTC)


async def sold_order(db: FakeDatabase, merchant: UUID, cents: int = 10000):
    order = order_created(lines=[(merchant, 1, cents)])
    order_id = UUID(order.payload["order_id"])
    payment_id = uuid4()
    await HandleOrderEvent(lambda: FakeUow(db), clock=lambda: NOW).handle(order)
    payments = HandlePaymentEvent(lambda: FakeUow(db), clock=lambda: NOW)
    await payments.handle(payment_confirmed(order_id, cents, payment_id))
    return order_id, payment_id, payments


async def test_a_refund_posts_a_reversal_that_zeroes_every_account() -> None:
    db = FakeDatabase()
    merchant = uuid4()
    order_id, payment_id, payments = await sold_order(db, merchant)
    assert db.balance(f"merchant:{merchant}") == 9000

    result = await payments.handle(payment_refunded(order_id, 10000, payment_id))

    assert result is HandleResult.PROCESSED
    assert {t.kind for t in db.transactions.values()} == {
        TransactionKind.PAYMENT,
        TransactionKind.REVERSAL,
    }
    assert db.balance("psp:receivable") == 0
    assert db.balance("platform:revenue") == 0
    assert db.balance(f"merchant:{merchant}") == 0
    reversal = next(t for t in db.transactions.values() if t.kind is TransactionKind.REVERSAL)
    assert reversal.total_debits == reversal.total_credits
    assert [type(e) for e in db.events] == [LedgerTransactionPosted, LedgerTransactionReversed]


async def test_refund_events_are_idempotent() -> None:
    db = FakeDatabase()
    order_id, payment_id, payments = await sold_order(db, uuid4())
    first = payment_refunded(order_id, 10000, payment_id)

    results = [
        await payments.handle(first),
        await payments.handle(first),
        await payments.handle(payment_refunded(order_id, 10000, payment_id)),
    ]

    assert results == [HandleResult.PROCESSED, HandleResult.DUPLICATE, HandleResult.DUPLICATE]
    assert len(db.transactions) == 2


async def test_a_refund_for_a_sale_that_was_never_posted_is_retried_not_dropped() -> None:
    db = FakeDatabase()
    order = order_created(lines=[(uuid4(), 1, 10000)])
    await HandleOrderEvent(lambda: FakeUow(db), clock=lambda: NOW).handle(order)
    payments = HandlePaymentEvent(lambda: FakeUow(db), clock=lambda: NOW)

    with pytest.raises(OrderProjectionNotFound):
        await payments.handle(payment_refunded(UUID(order.payload["order_id"]), 10000, uuid4()))

    assert db.transactions == {}


async def test_refund_with_the_wrong_amount_is_rejected() -> None:
    db = FakeDatabase()
    order_id, payment_id, payments = await sold_order(db, uuid4())

    result = await payments.handle(payment_refunded(order_id, 9999, payment_id))

    assert result is HandleResult.REJECTED
    assert len(db.transactions) == 1


async def test_merchant_summary_nets_out_the_refunded_sale() -> None:
    db = FakeDatabase()
    merchant = uuid4()
    await sold_order(db, merchant, 5000)
    order_id, payment_id, payments = await sold_order(db, merchant, 10000)
    await payments.handle(payment_refunded(order_id, 10000, payment_id))

    summary = await GetMerchantSummary(lambda: FakeUow(db), clock=lambda: NOW).execute(merchant, 1)

    assert summary.gross_sales_cents == 5000
    assert summary.net_sales_cents == 4500
    assert summary.platform_fees_cents == 500
    assert summary.orders_count == 1
    assert summary.balance_cents == 4500


def projection(lines: list[tuple[UUID, int, int]]) -> OrderProjection:
    return OrderProjection(
        order_id=uuid4(),
        currency="BRL",
        items=tuple(ProjectedItem(uuid4(), m, q, Money(p, "BRL")) for m, q, p in lines),
        created_at=NOW,
    )


@given(
    lines=st.lists(
        st.tuples(st.integers(0, 3), st.integers(1, 5), st.integers(1, 500_000)),
        min_size=1,
        max_size=6,
    ),
    bps=st.integers(0, 10_000),
)
def test_property_a_reversal_exactly_cancels_the_original_posting(lines, bps) -> None:
    merchants = [uuid4() for _ in range(4)]
    order = projection([(merchants[m], q, p) for m, q, p in lines])
    payment_id = uuid4()
    original = build_payment_transaction(order, payment_id, order.total, NOW, bps)
    reversal = build_reversal_transaction(order, payment_id, order.total, NOW, bps)

    combined: dict[str, int] = {}
    for tx in (original, reversal):
        for account, delta in tx.balance_deltas().items():
            combined[account.id] = combined.get(account.id, 0) + delta

    assert all(v == 0 for v in combined.values())
    assert reversal.total_debits == reversal.total_credits == original.total_debits
    assert reversal.platform_fee == original.platform_fee
