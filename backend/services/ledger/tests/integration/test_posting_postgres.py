import asyncio
import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, text

from ledger.application.errors import OrderProjectionNotFound
from ledger.application.handle_order_event import HandleOrderEvent
from ledger.application.handle_payment_event import HandlePaymentEvent
from ledger.application.results import HandleResult
from ledger.infrastructure.db.models import (
    EntryModel,
    InboxMessageModel,
    OrderProjectionModel,
    OutboxEventModel,
    TransactionModel,
)
from ledger.interface.api import create_app
from tests.auth import SECRET, as_user
from tests.builders import order_created, payment_confirmed
from tests.integration.helpers import balances, count, order_id_of, reconcile


async def place_order(order_handler, lines):
    event = order_created(lines=lines)
    assert await order_handler.handle(event) is HandleResult.PROCESSED
    return order_id_of(event), event.payload["total_cents"]


async def test_payment_is_posted_with_entries_balances_and_outbox_event(
    order_handler, payment_handler, session_factory, uow_factory
):
    merchant_a, merchant_b = uuid4(), uuid4()
    order_id, total = await place_order(
        order_handler, [(merchant_a, 1, 34990), (merchant_b, 3, 3335)]
    )

    result = await payment_handler.handle(payment_confirmed(order_id, total))

    assert result is HandleResult.PROCESSED
    assert await balances(session_factory) == {
        "psp:receivable": 44995,
        f"merchant:{merchant_a}": 34990 - 3499,
        f"merchant:{merchant_b}": 10005 - 1001,
        "platform:revenue": 3499 + 1001,
    }
    assert await count(session_factory, EntryModel) == 5
    async with session_factory() as session:
        outbox = (await session.execute(select(OutboxEventModel))).scalars().one()
    assert outbox.topic == "ledger.events"
    assert outbox.type == "LedgerTransactionPosted"
    assert outbox.key == str(order_id)
    assert outbox.payload["total_cents"] == 44995
    assert outbox.payload["platform_fee_cents"] == 4500
    report = await reconcile(uow_factory)
    assert report.balanced and report.accounts_consistent


async def test_order_projection_is_stored_once(order_handler, session_factory):
    event = order_created(lines=[(uuid4(), 2, 1000)])

    assert await order_handler.handle(event) is HandleResult.PROCESSED
    assert await order_handler.handle(event) is HandleResult.DUPLICATE
    again = order_created(order_id=order_id_of(event), lines=[(uuid4(), 1, 1)])
    assert await order_handler.handle(again) is HandleResult.DUPLICATE

    assert await count(session_factory, OrderProjectionModel) == 1
    async with session_factory() as session:
        stored = (await session.execute(select(OrderProjectionModel))).scalars().one()
    assert stored.total_cents == 2000


async def test_duplicate_payment_event_posts_once(order_handler, payment_handler, session_factory):
    order_id, total = await place_order(order_handler, [(uuid4(), 1, 5000)])
    event = payment_confirmed(order_id, total)

    assert await payment_handler.handle(event) is HandleResult.PROCESSED
    assert await payment_handler.handle(event) is HandleResult.DUPLICATE
    assert await payment_handler.handle(payment_confirmed(order_id, total)) is (
        HandleResult.DUPLICATE
    )

    assert await count(session_factory, TransactionModel) == 1
    assert (await balances(session_factory))["psp:receivable"] == 5000
    assert await count(session_factory, OutboxEventModel) == 1


async def test_concurrent_duplicates_of_the_same_order_post_exactly_once(
    order_handler, payment_handler, session_factory, uow_factory
):
    order_id, total = await place_order(order_handler, [(uuid4(), 1, 5000), (uuid4(), 2, 777)])

    results = await asyncio.gather(
        *[payment_handler.handle(payment_confirmed(order_id, total)) for _ in range(10)]
    )

    assert results.count(HandleResult.PROCESSED) == 1
    assert results.count(HandleResult.DUPLICATE) == 9
    assert await count(session_factory, TransactionModel) == 1
    assert (await balances(session_factory))["psp:receivable"] == total
    assert (await reconcile(uow_factory)).accounts_consistent


async def test_fifty_concurrent_payments_keep_the_merchant_balance_exact(
    order_handler, payment_handler, session_factory, uow_factory
):
    merchant, other_a, other_b = uuid4(), uuid4(), uuid4()
    orders = []
    for index in range(50):
        lines = [(merchant, 1, 10000)]
        if index % 3 == 1:
            lines.append((other_a, 1, 555))
        if index % 3 == 2:
            lines = [(other_b, 1, 333), *lines, (other_a, 2, 101)]
        orders.append(await place_order(order_handler, lines))

    results = await asyncio.gather(
        *[payment_handler.handle(payment_confirmed(oid, total)) for oid, total in orders]
    )

    assert set(results) == {HandleResult.PROCESSED}
    state = await balances(session_factory)
    assert state[f"merchant:{merchant}"] == 50 * 9000
    assert state["psp:receivable"] == sum(total for _, total in orders)
    merchants_and_platform = sum(v for k, v in state.items() if k != "psp:receivable")
    assert merchants_and_platform == state["psp:receivable"]
    assert await count(session_factory, TransactionModel) == 50
    report = await reconcile(uow_factory)
    assert report.balanced and report.accounts_consistent
    assert report.transactions_count == 50


async def test_payment_before_order_is_retried_and_then_posts(
    order_handler, payment_handler, session_factory
):
    order = order_created(lines=[(uuid4(), 1, 5000)])
    payment = payment_confirmed(order_id_of(order), 5000)

    with pytest.raises(OrderProjectionNotFound):
        await payment_handler.handle(payment)
    assert await count(session_factory, InboxMessageModel) == 0
    assert await count(session_factory, TransactionModel) == 0

    await order_handler.handle(order)
    assert await payment_handler.handle(payment) is HandleResult.PROCESSED
    assert await count(session_factory, TransactionModel) == 1


async def test_mismatching_payment_is_rejected_and_leaves_no_trace(
    order_handler, payment_handler, session_factory
):
    order_id, _ = await place_order(order_handler, [(uuid4(), 1, 5000)])

    assert await payment_handler.handle(payment_confirmed(order_id, 4999)) is HandleResult.REJECTED

    assert await count(session_factory, TransactionModel) == 0
    async with session_factory() as session:
        claimed = await session.scalar(
            select(func.count())
            .select_from(InboxMessageModel)
            .where(InboxMessageModel.consumer == "ledger-payments")
        )
    assert claimed == 0
    assert await balances(session_factory) == {}


async def test_database_refuses_non_positive_entries(
    order_handler, payment_handler, session_factory
):
    order_id, total = await place_order(order_handler, [(uuid4(), 1, 5000)])
    await payment_handler.handle(payment_confirmed(order_id, total))

    async with session_factory() as session:
        with pytest.raises(Exception, match="ck_entry_amount_positive"):
            await session.execute(
                text("update ledger_entries set amount_cents = 0 where direction = 'DEBIT'")
            )


async def test_random_orders_keep_the_books_closed(
    order_handler, payment_handler, session_factory, uow_factory
):
    rng = random.Random(20261111)
    merchants = [uuid4() for _ in range(4)]
    orders = []
    for _ in range(30):
        lines = [
            (rng.choice(merchants), rng.randint(1, 5), rng.randint(1, 250_000))
            for _ in range(rng.randint(1, 5))
        ]
        orders.append(await place_order(order_handler, lines))

    await asyncio.gather(
        *[payment_handler.handle(payment_confirmed(oid, total)) for oid, total in orders]
    )

    state = await balances(session_factory)
    received = sum(total for _, total in orders)
    assert state["psp:receivable"] == received
    assert sum(v for k, v in state.items() if k != "psp:receivable") == received
    report = await reconcile(uow_factory)
    assert report.balanced and report.accounts_consistent
    assert report.total_debits_cents == report.total_credits_cents == received


async def test_reconciliation_detects_a_balance_that_drifted(
    order_handler, payment_handler, session_factory, uow_factory
):
    order_id, total = await place_order(order_handler, [(uuid4(), 1, 5000)])
    await payment_handler.handle(payment_confirmed(order_id, total))
    async with session_factory() as session:
        await session.execute(
            text(
                "update accounts set balance_cents = balance_cents + 1 "
                "where id = 'platform:revenue'"
            )
        )
        await session.commit()

    report = await reconcile(uow_factory)

    assert report.balanced
    assert not report.accounts_consistent
    assert report.inconsistent_accounts == ["platform:revenue"]


async def test_api_summary_and_entries_against_postgres(
    order_handler, payment_handler, uow_factory
):
    now = datetime.now(UTC)
    merchant = uuid4()
    for days_ago, cents in [(0, 10000), (0, 2005), (3, 5000)]:
        when = now - timedelta(days=days_ago)
        event = order_created(lines=[(merchant, 1, cents)])
        await HandleOrderEvent(uow_factory, clock=lambda w=when: w).handle(event)
        await HandlePaymentEvent(uow_factory, clock=lambda w=when: w).handle(
            payment_confirmed(order_id_of(event), cents)
        )
    app = create_app(uow_factory=uow_factory, internal_secret=SECRET)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://t", headers=as_user(("admin",))
    ) as client:
        summary = (await client.get(f"/merchants/{merchant}/summary", params={"days": 7})).json()
        page = (
            await client.get(
                f"/accounts/merchant:{merchant}/entries", params={"page": 1, "page_size": 2}
            )
        ).json()
        reconciliation = (await client.get("/reconciliation")).json()

    assert len(summary["daily"]) == 7
    days = [d["date"] for d in summary["daily"]]
    assert days == sorted(days)
    today = summary["daily"][-1]
    assert (today["gross_cents"], today["net_cents"], today["orders"]) == (12005, 10804, 2)
    assert summary["daily"][-4]["gross_cents"] == 5000
    assert sum(1 for d in summary["daily"] if d["orders"] == 0) == 5
    assert summary["gross_sales_cents"] == 17005
    assert summary["platform_fees_cents"] == 1000 + 201 + 500
    assert summary["balance_cents"] == summary["net_sales_cents"] == 17005 - 1701
    assert summary["orders_count"] == 3
    assert (page["total"], len(page["items"])) == (3, 2)
    assert page["items"][0]["created_at"] >= page["items"][1]["created_at"]
    assert reconciliation["balanced"] and reconciliation["accounts_consistent"]


async def test_summary_for_unknown_merchant_is_zeroed(uow_factory):
    app = create_app(uow_factory=uow_factory, internal_secret=SECRET)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://t", headers=as_user(("admin",))
    ) as client:
        body = (await client.get(f"/merchants/{uuid4()}/summary", params={"days": 3})).json()
    assert body["balance_cents"] == 0
    assert [d["orders"] for d in body["daily"]] == [0, 0, 0]


async def test_two_merchants_are_isolated_against_a_real_database(
    order_handler, payment_handler, uow_factory
):
    shop_a, shop_b = uuid4(), uuid4()
    for shop, cents in ((shop_a, 10000), (shop_b, 77700)):
        order_id, total = await place_order(order_handler, [(shop, 1, cents)])
        await payment_handler.handle(payment_confirmed(order_id, total))
    app = create_app(uow_factory=uow_factory, internal_secret=SECRET)
    transport = httpx.ASGITransport(app=app)
    seller_a = as_user(("merchant",), merchant_id=shop_a)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        own = await client.get(f"/merchants/{shop_a}/summary", headers=seller_a)
        entries = await client.get(f"/accounts/merchant:{shop_a}/entries", headers=seller_a)
        cross = await client.get(f"/merchants/{shop_b}/summary", headers=seller_a)
        cross_entries = await client.get(f"/accounts/merchant:{shop_b}/entries", headers=seller_a)
        platform = await client.get("/accounts/platform:revenue/entries", headers=seller_a)
        recon = await client.get("/reconciliation", headers=seller_a)
    assert own.json()["gross_sales_cents"] == 10000
    assert entries.status_code == 200 and entries.json()["total"] >= 1
    assert (cross.status_code, cross_entries.status_code) == (403, 403)
    assert (platform.status_code, recon.status_code) == (403, 403)
    assert "77700" not in cross.text + cross_entries.text
