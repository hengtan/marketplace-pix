from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from ledger.application.errors import OrderProjectionNotFound
from ledger.application.handle_order_event import HandleOrderEvent
from ledger.application.handle_payment_event import HandlePaymentEvent
from ledger.application.ports import IncomingEvent
from ledger.application.queries import Reconcile
from ledger.application.results import HandleResult
from tests.builders import order_created, payment_confirmed
from tests.fakes import FakeDatabase, FakeUow

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


@pytest.fixture
def db():
    return FakeDatabase()


@pytest.fixture
def orders(db):
    return HandleOrderEvent(lambda: FakeUow(db), clock=lambda: NOW)


@pytest.fixture
def payments(db):
    return HandlePaymentEvent(lambda: FakeUow(db), clock=lambda: NOW)


async def test_order_created_stores_the_projection(orders, db):
    merchant_a, merchant_b = uuid4(), uuid4()
    event = order_created(lines=[(merchant_a, 2, 1000), (merchant_b, 1, 500), (merchant_a, 1, 250)])

    assert await orders.handle(event) is HandleResult.PROCESSED

    projection = db.projections[UUID(event.payload["order_id"])]
    assert projection.currency == "BRL"
    assert projection.total.cents == 2750
    assert {m: s.cents for m, s in projection.merchant_subtotals().items()} == {
        merchant_a: 2250,
        merchant_b: 500,
    }


async def test_redelivered_order_created_is_a_duplicate(orders, db):
    event = order_created()
    assert await orders.handle(event) is HandleResult.PROCESSED
    assert await orders.handle(event) is HandleResult.DUPLICATE
    assert len(db.projections) == 1


async def test_same_order_with_another_event_id_does_not_overwrite(orders, db):
    first = order_created()
    order_id = UUID(first.payload["order_id"])
    await orders.handle(first)

    again = order_created(order_id=order_id, lines=[(uuid4(), 1, 1)])
    assert await orders.handle(again) is HandleResult.DUPLICATE

    assert db.projections[order_id].total.cents == 10000


async def test_unrelated_and_malformed_events_are_not_projected(orders, db):
    other = IncomingEvent(uuid4(), "OrderPaid", "x", {"order_id": str(uuid4())})
    broken = IncomingEvent(uuid4(), "OrderCreated", "x", {"order_id": "nope"})
    empty = IncomingEvent(
        uuid4(), "OrderCreated", "x", {"order_id": str(uuid4()), "currency": "BRL", "items": []}
    )

    assert await orders.handle(other) is HandleResult.IGNORED
    assert await orders.handle(broken) is HandleResult.REJECTED
    assert await orders.handle(empty) is HandleResult.REJECTED
    assert db.projections == {}


async def test_payment_confirmed_posts_a_balanced_split_transaction(orders, payments, db):
    merchant_a, merchant_b = uuid4(), uuid4()
    order = order_created(lines=[(merchant_a, 1, 34990), (merchant_b, 3, 3335)])
    order_id = UUID(order.payload["order_id"])
    await orders.handle(order)

    result = await payments.handle(payment_confirmed(order_id, 34990 + 10005))

    assert result is HandleResult.PROCESSED
    transaction = db.transaction_for_order(order_id)
    assert transaction.total_debits == transaction.total_credits
    assert db.balance("psp:receivable") == 44995
    assert db.balance(f"merchant:{merchant_a}") == 34990 - 3499
    assert db.balance(f"merchant:{merchant_b}") == 10005 - 1001
    assert db.balance("platform:revenue") == 3499 + 1001
    (event,) = db.events
    assert event.total_cents == 44995
    assert event.platform_fee_cents == 4500


async def test_duplicate_payment_event_posts_once(orders, payments, db):
    order = order_created(lines=[(uuid4(), 1, 5000)])
    order_id = UUID(order.payload["order_id"])
    await orders.handle(order)
    event = payment_confirmed(order_id, 5000)

    assert await payments.handle(event) is HandleResult.PROCESSED
    assert await payments.handle(event) is HandleResult.DUPLICATE

    assert len(db.transactions) == 1
    assert db.balance("psp:receivable") == 5000
    assert len(db.events) == 1


async def test_second_payment_for_the_same_order_is_idempotent(orders, payments, db):
    order = order_created(lines=[(uuid4(), 1, 5000)])
    order_id = UUID(order.payload["order_id"])
    await orders.handle(order)
    payment_id = uuid4()

    assert await payments.handle(payment_confirmed(order_id, 5000, payment_id)) is (
        HandleResult.PROCESSED
    )
    assert await payments.handle(payment_confirmed(order_id, 5000, payment_id)) is (
        HandleResult.DUPLICATE
    )
    assert await payments.handle(payment_confirmed(order_id, 5000)) is HandleResult.DUPLICATE

    assert len(db.transactions) == 1
    assert db.balance("psp:receivable") == 5000


async def test_payment_before_order_raises_and_succeeds_on_retry(orders, payments, db):
    order = order_created(lines=[(uuid4(), 1, 5000)])
    order_id = UUID(order.payload["order_id"])
    payment = payment_confirmed(order_id, 5000)

    with pytest.raises(OrderProjectionNotFound):
        await payments.handle(payment)
    assert db.transactions == {}
    assert db.inbox == set()

    await orders.handle(order)
    assert await payments.handle(payment) is HandleResult.PROCESSED
    assert len(db.transactions) == 1


async def test_payment_with_wrong_amount_or_currency_is_rejected_without_effects(
    orders, payments, db
):
    order = order_created(lines=[(uuid4(), 1, 5000)])
    order_id = UUID(order.payload["order_id"])
    await orders.handle(order)

    assert await payments.handle(payment_confirmed(order_id, 4999)) is HandleResult.REJECTED
    assert (
        await payments.handle(payment_confirmed(order_id, 5000, currency="USD"))
        is HandleResult.REJECTED
    )

    assert db.transactions == {}
    assert db.accounts == {}


async def test_other_payment_events_are_ignored(payments, db):
    event = IncomingEvent(uuid4(), "PaymentExpired", "x", {"order_id": str(uuid4())})
    assert await payments.handle(event) is HandleResult.IGNORED


async def test_reconciliation_is_balanced_after_many_payments(orders, payments, db):
    for index in range(10):
        order = order_created(lines=[(uuid4(), index + 1, 333 + index)])
        await orders.handle(order)
        await payments.handle(
            payment_confirmed(UUID(order.payload["order_id"]), order.payload["total_cents"])
        )

    report = await Reconcile(lambda: FakeUow(db), clock=lambda: NOW).execute()

    assert report.balanced
    assert report.accounts_consistent
    assert report.transactions_count == 10
    assert report.total_debits_cents == report.total_credits_cents > 0


async def test_reconciliation_flags_a_tampered_balance(orders, payments, db):
    order = order_created(lines=[(uuid4(), 1, 5000)])
    await orders.handle(order)
    await payments.handle(payment_confirmed(UUID(order.payload["order_id"]), 5000))
    account, currency, balance = db.accounts["platform:revenue"]
    db.accounts["platform:revenue"] = (account, currency, balance + 1)

    report = await Reconcile(lambda: FakeUow(db), clock=lambda: NOW).execute()

    assert report.balanced
    assert not report.accounts_consistent
    assert report.inconsistent_accounts == ["platform:revenue"]
