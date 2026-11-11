from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from ledger.application.handle_order_event import HandleOrderEvent
from ledger.application.handle_payment_event import HandlePaymentEvent
from ledger.interface.api import create_app
from tests.auth import SECRET, as_user
from tests.builders import order_created, payment_confirmed
from tests.fakes import FakeDatabase, FakeUow

NOW = datetime(2026, 11, 11, 15, 30, tzinfo=UTC)


async def sell(db: FakeDatabase, merchant: UUID, cents: int) -> None:
    order = order_created(lines=[(merchant, 1, cents)])
    order_id = UUID(order.payload["order_id"])
    await HandleOrderEvent(lambda: FakeUow(db), clock=lambda: NOW).handle(order)
    await HandlePaymentEvent(lambda: FakeUow(db), clock=lambda: NOW).handle(
        payment_confirmed(order_id, cents)
    )


@pytest.fixture
async def env():
    db = FakeDatabase()
    shop_a, shop_b = uuid4(), uuid4()
    await sell(db, shop_a, 10000)
    await sell(db, shop_b, 50000)
    app = create_app(uow_factory=lambda: FakeUow(db), clock=lambda: NOW, internal_secret=SECRET)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield client, shop_a, shop_b


async def test_every_endpoint_requires_authentication(env):
    client, shop_a, _ = env
    for path in (
        f"/merchants/{shop_a}/summary",
        f"/accounts/merchant:{shop_a}/entries",
        "/reconciliation",
    ):
        assert (await client.get(path)).status_code == 401


async def test_merchants_are_isolated_in_the_summary(env):
    client, shop_a, shop_b = env
    seller_a = as_user(("merchant",), merchant_id=shop_a)
    seller_b = as_user(("merchant",), merchant_id=shop_b)
    own = await client.get(f"/merchants/{shop_a}/summary", headers=seller_a)
    assert own.status_code == 200 and own.json()["gross_sales_cents"] == 10000
    cross = await client.get(f"/merchants/{shop_b}/summary", headers=seller_a)
    assert cross.status_code == 403
    assert "50000" not in cross.text
    reverse = await client.get(f"/merchants/{shop_b}/summary", headers=seller_b)
    assert reverse.json()["gross_sales_cents"] == 50000


async def test_merchants_are_isolated_in_the_entries(env):
    client, shop_a, shop_b = env
    seller_a = as_user(("merchant",), merchant_id=shop_a)
    own = await client.get(f"/accounts/merchant:{shop_a}/entries", headers=seller_a)
    assert own.status_code == 200 and own.json()["total"] >= 1
    for account in (
        f"merchant:{shop_b}",
        "platform:revenue",
        "psp:receivable",
        "merchant:not-a-uuid",
    ):
        denied = await client.get(f"/accounts/{account}/entries", headers=seller_a)
        assert denied.status_code == 403, account


async def test_a_customer_has_no_ledger_access(env):
    client, shop_a, _ = env
    customer = as_user(("customer",))
    assert (await client.get(f"/merchants/{shop_a}/summary", headers=customer)).status_code == 403


async def test_a_merchant_token_without_merchant_binding_is_denied(env):
    client, shop_a, _ = env
    unbound = as_user(("merchant",))
    assert (await client.get(f"/merchants/{shop_a}/summary", headers=unbound)).status_code == 403


async def test_reconciliation_is_admin_only(env):
    client, shop_a, _ = env
    seller = as_user(("merchant",), merchant_id=shop_a)
    assert (await client.get("/reconciliation", headers=seller)).status_code == 403
    admin = await client.get("/reconciliation", headers=as_user(("admin",)))
    assert admin.status_code == 200 and admin.json()["balanced"] is True


async def test_admin_reads_every_merchant_and_platform_accounts(env):
    client, shop_a, shop_b = env
    admin = as_user(("admin",))
    assert (await client.get(f"/merchants/{shop_b}/summary", headers=admin)).status_code == 200
    assert (
        await client.get("/accounts/platform:revenue/entries", headers=admin)
    ).status_code == 200


async def test_forged_and_replayed_identity_is_ignored(env):
    client, shop_a, shop_b = env
    seller_a = as_user(("merchant",), merchant_id=shop_a)
    forged = {**seller_a, "x-merchant-id": str(shop_b)}
    assert (await client.get(f"/merchants/{shop_b}/summary", headers=forged)).status_code == 401
    other_request = {**seller_a, "x-request-id": "another"}
    assert (
        await client.get(f"/merchants/{shop_a}/summary", headers=other_request)
    ).status_code == 401
