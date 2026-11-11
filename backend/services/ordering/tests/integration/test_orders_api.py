import asyncio
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ordering.infrastructure.db.models import OrderModel, OutboxEventModel
from ordering.interface.api import create_app
from tests.fakes import FakeCatalog

PRODUCTS = [uuid4(), uuid4()]


@pytest.fixture
async def client(uow_factory):
    catalog = FakeCatalog({PRODUCTS[0]: 1990, PRODUCTS[1]: 500})
    app = create_app(uow_factory=uow_factory, catalog=catalog)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def body(customer_id=None):
    return {
        "customer_id": str(customer_id or uuid4()),
        "customer_name": "Maria Souza",
        "customer_email": "maria@example.com",
        "items": [
            {"product_id": str(PRODUCTS[0]), "quantity": 2},
            {"product_id": str(PRODUCTS[1]), "quantity": 1},
        ],
    }


async def count(session_factory, model) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def test_create_then_get_roundtrip_in_real_database(client):
    created = await client.post("/orders", json=body(), headers={"Idempotency-Key": "k1"})
    assert created.status_code == 201

    fetched = (await client.get(f"/orders/{created.json()['id']}")).json()
    assert fetched["total_cents"] == 4480
    assert len(fetched["items"]) == 2
    assert fetched["created_at"] and fetched["customer_name"] == "Maria Souza"


async def test_replay_does_not_duplicate_order_or_event(client, session_factory):
    payload, headers = body(), {"Idempotency-Key": "k1"}

    first = await client.post("/orders", json=payload, headers=headers)
    second = await client.post("/orders", json=payload, headers=headers)

    assert second.json() == first.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    assert await count(session_factory, OrderModel) == 1
    assert await count(session_factory, OutboxEventModel) == 1


async def test_concurrent_requests_with_same_key_create_exactly_one_order(client, session_factory):
    payload, headers = body(), {"Idempotency-Key": "same-key"}

    responses = await asyncio.gather(
        *(client.post("/orders", json=payload, headers=headers) for _ in range(5))
    )

    assert {r.status_code for r in responses} == {201}
    assert len({r.json()["id"] for r in responses}) == 1
    assert sum(1 for r in responses if r.headers.get("Idempotent-Replayed") == "true") == 4
    assert await count(session_factory, OrderModel) == 1
    assert await count(session_factory, OutboxEventModel) == 1


async def test_same_key_with_different_body_is_rejected(client, session_factory):
    headers = {"Idempotency-Key": "k1"}
    await client.post("/orders", json=body(), headers=headers)

    response = await client.post("/orders", json=body(), headers=headers)

    assert response.status_code == 422
    assert await count(session_factory, OrderModel) == 1


async def test_list_orders_returns_only_the_customers_orders_newest_first(client):
    mine = uuid4()
    ids = []
    for n in range(3):
        created = await client.post(
            "/orders", json=body(mine), headers={"Idempotency-Key": f"m{n}"}
        )
        ids.append(created.json()["id"])
    await client.post("/orders", json=body(), headers={"Idempotency-Key": "other"})

    page = (await client.get("/orders", params={"customer_id": str(mine), "page_size": 2})).json()

    assert page["total"] == 3 and len(page["items"]) == 2
    assert [o["id"] for o in page["items"]] == [ids[2], ids[1]]
    assert (await client.get("/orders", params={"customer_id": str(uuid4())})).json()["total"] == 0
