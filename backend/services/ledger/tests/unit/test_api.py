from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest

from ledger.application.handle_order_event import HandleOrderEvent
from ledger.application.handle_payment_event import HandlePaymentEvent
from ledger.interface.api import create_app
from tests.auth import SECRET, as_user
from tests.builders import order_created, payment_confirmed
from tests.fakes import FakeDatabase, FakeUow

TODAY = datetime(2026, 11, 11, 15, 30, tzinfo=UTC)


async def sell(db, merchant, cents, when):
    order = order_created(lines=[(merchant, 1, cents)])
    order_id = UUID(order.payload["order_id"])
    await HandleOrderEvent(lambda: FakeUow(db), clock=lambda: when).handle(order)
    await HandlePaymentEvent(lambda: FakeUow(db), clock=lambda: when).handle(
        payment_confirmed(order_id, cents)
    )
    return order_id


@pytest.fixture
async def env():
    db = FakeDatabase()
    app = create_app(uow_factory=lambda: FakeUow(db), clock=lambda: TODAY, internal_secret=SECRET)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://t", headers=as_user(("admin",))
    ) as client:
        yield client, db


async def test_summary_endpoint_returns_every_day_in_order_including_days_without_sales(env):
    client, db = env
    merchant = uuid4()
    await sell(db, merchant, 10000, TODAY)
    await sell(db, merchant, 2000, TODAY - timedelta(days=2))

    response = await client.get(f"/merchants/{merchant}/summary", params={"days": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["merchant_id"] == str(merchant)
    assert body["currency"] == "BRL"
    assert body["balance_cents"] == 9000 + 1800
    assert body["gross_sales_cents"] == 12000
    assert body["platform_fees_cents"] == 1200
    assert body["net_sales_cents"] == 10800
    assert body["orders_count"] == 2
    assert body["daily"] == [
        {"date": "2026-11-07", "gross_cents": 0, "net_cents": 0, "orders": 0},
        {"date": "2026-11-08", "gross_cents": 0, "net_cents": 0, "orders": 0},
        {"date": "2026-11-09", "gross_cents": 2000, "net_cents": 1800, "orders": 1},
        {"date": "2026-11-10", "gross_cents": 0, "net_cents": 0, "orders": 0},
        {"date": "2026-11-11", "gross_cents": 10000, "net_cents": 9000, "orders": 1},
    ]


async def test_summary_defaults_to_thirty_days_and_validates_input(env):
    client, _ = env
    merchant = uuid4()

    body = (await client.get(f"/merchants/{merchant}/summary")).json()

    assert len(body["daily"]) == 30
    assert body["daily"][0]["date"] == str(date(2026, 11, 11) - timedelta(days=29))
    assert (
        await client.get(f"/merchants/{merchant}/summary", params={"days": 0})
    ).status_code == 422
    assert (await client.get("/merchants/not-a-uuid/summary")).status_code == 422


async def test_entries_endpoint_paginates_most_recent_first(env):
    client, db = env
    merchant = uuid4()
    for index in range(5):
        await sell(db, merchant, 1000 + index, TODAY - timedelta(hours=5 - index))

    response = await client.get(
        f"/accounts/merchant:{merchant}/entries", params={"page": 2, "page_size": 2}
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["page"], body["page_size"]) == (5, 2, 2)
    assert [item["amount_cents"] for item in body["items"]] == [902, 901]
    assert set(body["items"][0]) == {
        "id",
        "transaction_id",
        "direction",
        "amount_cents",
        "description",
        "order_id",
        "created_at",
    }
    assert (
        await client.get("/accounts/psp:receivable/entries", params={"page_size": 500})
    ).status_code == 422


async def test_reconciliation_endpoint(env):
    client, db = env
    await sell(db, uuid4(), 12345, TODAY)
    await sell(db, uuid4(), 1, TODAY)

    body = (await client.get("/reconciliation")).json()

    assert body["balanced"] is True
    assert body["total_debits_cents"] == body["total_credits_cents"] == 12346
    assert body["transactions_count"] == 2
    assert body["accounts_consistent"] is True
    assert body["checked_at"].startswith("2026-11-11T15:30")


async def test_health_and_ready(env):
    client, _ = env
    assert (await client.get("/health")).json() == {"status": "ok"}
    assert (await client.get("/ready")).status_code == 200
