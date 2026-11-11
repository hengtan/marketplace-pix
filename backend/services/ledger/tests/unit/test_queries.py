from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from ledger.application.errors import InvalidQuery
from ledger.application.handle_order_event import HandleOrderEvent
from ledger.application.handle_payment_event import HandlePaymentEvent
from ledger.application.queries import GetMerchantSummary, ListAccountEntries
from tests.builders import order_created, payment_confirmed
from tests.fakes import FakeDatabase, FakeUow

TODAY = datetime(2026, 11, 11, 15, 30, tzinfo=UTC)


async def sell(db, merchant, cents, when, other=None):
    lines = [(merchant, 1, cents)] + ([(other, 1, 1000)] if other else [])
    order = order_created(lines=lines)
    order_id = UUID(order.payload["order_id"])
    await HandleOrderEvent(lambda: FakeUow(db), clock=lambda: when).handle(order)
    await HandlePaymentEvent(lambda: FakeUow(db), clock=lambda: when).handle(
        payment_confirmed(order_id, order.payload["total_cents"])
    )
    return order_id


@pytest.fixture
def db():
    return FakeDatabase()


def summary_use_case(db):
    return GetMerchantSummary(lambda: FakeUow(db), clock=lambda: TODAY)


async def test_summary_for_a_merchant_without_sales_is_all_zeros_with_every_day(db):
    summary = await summary_use_case(db).execute(uuid4(), days=7)

    assert summary.balance_cents == 0
    assert summary.currency == "BRL"
    assert summary.orders_count == 0
    assert len(summary.daily) == 7
    assert all(d.gross_cents == d.net_cents == d.orders == 0 for d in summary.daily)


async def test_summary_has_a_zeroed_chronological_series_with_gaps(db):
    merchant = uuid4()
    await sell(db, merchant, 10000, TODAY)
    await sell(db, merchant, 5000, TODAY - timedelta(days=3), other=uuid4())
    await sell(db, merchant, 2005, TODAY - timedelta(days=3))
    await sell(db, merchant, 99999, TODAY - timedelta(days=40))
    await sell(db, uuid4(), 777, TODAY)

    summary = await summary_use_case(db).execute(merchant, days=30)

    assert [d.day for d in summary.daily] == [
        date(2026, 11, 11) - timedelta(days=29 - i) for i in range(30)
    ]
    by_day = {d.day: d for d in summary.daily}
    assert (by_day[date(2026, 11, 11)].gross_cents, by_day[date(2026, 11, 11)].net_cents) == (
        10000,
        9000,
    )
    assert by_day[date(2026, 11, 11)].orders == 1
    assert (by_day[date(2026, 11, 8)].gross_cents, by_day[date(2026, 11, 8)].orders) == (7005, 2)
    assert by_day[date(2026, 11, 10)].gross_cents == 0
    assert summary.gross_sales_cents == 17005
    assert summary.platform_fees_cents == 1000 + 500 + 201
    assert summary.net_sales_cents == 17005 - 1701
    assert summary.orders_count == 3
    assert summary.balance_cents == 17005 - 1701 + (99999 - 10000)


async def test_summary_rejects_invalid_days(db):
    with pytest.raises(InvalidQuery):
        await summary_use_case(db).execute(uuid4(), days=0)
    with pytest.raises(InvalidQuery):
        await summary_use_case(db).execute(uuid4(), days=366)


async def test_entries_are_paginated_most_recent_first(db):
    merchant = uuid4()
    for index in range(5):
        await sell(db, merchant, 1000 + index, TODAY - timedelta(hours=5 - index))
    use_case = ListAccountEntries(lambda: FakeUow(db))

    first = await use_case.execute(f"merchant:{merchant}", page=1, page_size=2)
    last = await use_case.execute(f"merchant:{merchant}", page=3, page_size=2)

    assert first.total == 5
    assert [e.amount_cents for e in first.items] == [1004 - 100, 1003 - 100]
    assert [e.amount_cents for e in last.items] == [1000 - 100]
    assert all(e.direction == "CREDIT" for e in first.items)


async def test_entries_of_unknown_account_are_empty_and_bad_paging_is_rejected(db):
    use_case = ListAccountEntries(lambda: FakeUow(db))
    page = await use_case.execute("merchant:" + str(uuid4()))
    assert (page.items, page.total) == ([], 0)
    with pytest.raises(InvalidQuery):
        await use_case.execute("psp:receivable", page=0)
    with pytest.raises(InvalidQuery):
        await use_case.execute("psp:receivable", page_size=101)
