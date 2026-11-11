from uuid import uuid4

import httpx
import pytest
from prometheus_client import REGISTRY

from ordering.interface.api import create_app
from tests.fakes import FakeCatalog, FakeDatabase, FakeUow

PRODUCT = uuid4()


@pytest.fixture
def db():
    return FakeDatabase()


@pytest.fixture
def catalog():
    return FakeCatalog({PRODUCT: 1990})


@pytest.fixture
async def client(db, catalog):
    app = create_app(uow_factory=lambda: FakeUow(db), catalog=catalog)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def body(quantity=2, customer_id=None):
    return {
        "customer_id": str(customer_id or uuid4()),
        "customer_name": "Maria Souza",
        "customer_email": "maria@example.com",
        "items": [{"product_id": str(PRODUCT), "quantity": quantity}],
    }


async def test_post_creates_order_with_catalog_price_and_get_returns_it(client):
    payload = body()
    created = await client.post("/orders", json=payload, headers={"Idempotency-Key": "k1"})
    assert created.status_code == 201

    data = (await client.get(f"/orders/{created.json()['id']}")).json()
    assert data["status"] == "PENDING"
    assert data["total_cents"] == 3980
    assert data["customer_email"] == "maria@example.com"
    assert data["cancel_reason"] is None
    assert data["items"][0]["unit_price_cents"] == 1990
    assert data["items"][0]["merchant_id"]


async def test_price_sent_by_the_client_is_ignored(client):
    payload = body()
    payload["items"][0]["unit_price_cents"] = 1
    created = await client.post("/orders", json=payload, headers={"Idempotency-Key": "k1"})

    data = (await client.get(f"/orders/{created.json()['id']}")).json()
    assert data["total_cents"] == 3980


async def test_missing_idempotency_key_is_400(client):
    assert (await client.post("/orders", json=body())).status_code == 400


async def test_replay_returns_same_id_and_marks_header(client, db):
    payload, headers = body(), {"Idempotency-Key": "k1"}

    first = await client.post("/orders", json=payload, headers=headers)
    second = await client.post("/orders", json=payload, headers=headers)

    assert second.status_code == 201 and second.json() == first.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first.headers
    assert len(db.orders) == 1


async def test_same_key_with_different_body_is_422(client):
    headers = {"Idempotency-Key": "k1"}
    await client.post("/orders", json=body(1), headers=headers)
    assert (await client.post("/orders", json=body(5), headers=headers)).status_code == 422


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["items"][0].update(quantity=0),
        lambda b: b.update(items=[]),
        lambda b: b.update(customer_email="not-an-email"),
        lambda b: b.update(customer_name=""),
    ],
)
async def test_invalid_bodies_are_422(client, mutate):
    payload = body()
    mutate(payload)
    assert (
        await client.post("/orders", json=payload, headers={"Idempotency-Key": "k"})
    ).status_code == 422


async def test_unknown_product_is_422(client, catalog):
    catalog.unknown.add(PRODUCT)
    response = await client.post("/orders", json=body(), headers={"Idempotency-Key": "k1"})
    assert response.status_code == 422 and "unknown product" in response.json()["detail"]


async def test_catalog_down_is_503(client, catalog):
    catalog.fail = True
    response = await client.post("/orders", json=body(), headers={"Idempotency-Key": "k1"})
    assert response.status_code == 503


async def test_unknown_order_is_404(client):
    assert (await client.get(f"/orders/{uuid4()}")).status_code == 404


async def test_list_orders_is_scoped_to_the_customer_and_paginated(client):
    mine, other = uuid4(), uuid4()
    for n in range(3):
        await client.post(
            "/orders", json=body(customer_id=mine), headers={"Idempotency-Key": f"m{n}"}
        )
    await client.post("/orders", json=body(customer_id=other), headers={"Idempotency-Key": "o1"})

    page1 = (await client.get("/orders", params={"customer_id": str(mine), "page_size": 2})).json()
    page2 = (
        await client.get("/orders", params={"customer_id": str(mine), "page": 2, "page_size": 2})
    ).json()

    assert page1["total"] == 3 and len(page1["items"]) == 2 and page1["page"] == 1
    assert len(page2["items"]) == 1
    assert all(o["customer_id"] == str(mine) for o in page1["items"] + page2["items"])


async def test_list_requires_customer_id(client):
    assert (await client.get("/orders")).status_code == 422


async def test_health(client):
    assert (await client.get("/health")).json() == {"status": "ok"}


async def test_orders_created_counter_counts_new_orders_but_not_replays(client):
    before = REGISTRY.get_sample_value("marketplace_orders_created_total") or 0.0
    payload, headers = body(), {"Idempotency-Key": "metric-key"}

    await client.post("/orders", json=payload, headers=headers)
    await client.post("/orders", json=payload, headers=headers)

    assert (REGISTRY.get_sample_value("marketplace_orders_created_total") or 0.0) - before == 1
