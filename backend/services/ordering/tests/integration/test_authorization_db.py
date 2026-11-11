from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from ordering.interface.api import create_app
from tests.auth import SECRET, as_user
from tests.fakes import FakeCatalog, merchant_of

PRODUCT_A, PRODUCT_B = uuid4(), uuid4()


@pytest.fixture
async def client(uow_factory):
    app = create_app(
        uow_factory=uow_factory,
        catalog=FakeCatalog({PRODUCT_A: 1000, PRODUCT_B: 2000}),
        internal_secret=SECRET,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def order_body(*products):
    return {
        "customer_name": "Maria",
        "customer_email": "maria@example.com",
        "items": [{"product_id": str(p), "quantity": 1} for p in products],
    }


async def place(client, headers, key, *products):
    response = await client.post(
        "/orders", json=order_body(*products), headers={**headers, "Idempotency-Key": key}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_idor_is_blocked_with_a_real_database(client):
    alice, bob = uuid4(), uuid4()
    order_id = await place(client, as_user(user_id=alice), "k1", PRODUCT_A)
    assert (
        await client.get(f"/orders/{order_id}", headers=as_user(user_id=alice))
    ).status_code == 200
    assert (
        await client.get(f"/orders/{order_id}", headers=as_user(user_id=bob))
    ).status_code == 404
    assert (await client.get(f"/orders/{order_id}")).status_code == 404
    assert (await client.get("/orders", headers=as_user(user_id=bob))).json()["total"] == 0
    assert (await client.get("/orders", headers=as_user(user_id=alice))).json()["total"] == 1


async def test_guest_orders_are_isolated_from_account_orders(client):
    shared = uuid4()
    guest_order = await client.post(
        "/orders",
        json={**order_body(PRODUCT_A), "customer_id": str(shared)},
        headers={"Idempotency-Key": "g1"},
    )
    assert guest_order.status_code == 201
    assert (await client.get(f"/orders?customer_id={shared}")).json()["total"] == 1
    assert (await client.get("/orders", headers=as_user(user_id=shared))).json()["total"] == 0


async def test_merchant_isolation_with_a_real_database(client):
    shop_a, shop_b = merchant_of(PRODUCT_A), merchant_of(PRODUCT_B)
    await place(client, as_user(), "o1", PRODUCT_A, PRODUCT_B)
    await place(client, as_user(), "o2", PRODUCT_B)
    seller_a = as_user(("merchant",), merchant_id=shop_a)
    seller_b = as_user(("merchant",), merchant_id=shop_b)
    a = (await client.get("/orders/merchant", headers=seller_a)).json()
    b = (await client.get("/orders/merchant", headers=seller_b)).json()
    assert (a["total"], b["total"]) == (1, 2)
    assert {i["merchant_id"] for o in a["items"] for i in o["items"]} == {str(shop_a)}
    assert {i["merchant_id"] for o in b["items"] for i in o["items"]} == {str(shop_b)}
    assert a["items"][0]["subtotal_cents"] == 1000
