import asyncio
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ordering.infrastructure.db.models import OrderModel, OutboxEventModel
from ordering.interface.api import create_app


@pytest.fixture
async def client(uow_factory):
    app = create_app(uow_factory=uow_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def body(customer_id=None):
    return {
        "customer_id": str(customer_id or uuid4()),
        "items": [
            {"product_id": str(uuid4()), "quantity": 2, "unit_price_cents": 1990},
            {"product_id": str(uuid4()), "quantity": 1, "unit_price_cents": 500},
        ],
    }


async def count(session_factory, model) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def test_create_then_get_roundtrip_in_real_database(client):
    created = await client.post("/orders", json=body(), headers={"Idempotency-Key": "k1"})
    assert created.status_code == 201

    fetched = await client.get(f"/orders/{created.json()['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["total_cents"] == 4480
    assert len(fetched.json()["items"]) == 2


async def test_replay_does_not_duplicate_order_or_event(client, session_factory):
    payload = body()
    headers = {"Idempotency-Key": "k1"}

    first = await client.post("/orders", json=payload, headers=headers)
    second = await client.post("/orders", json=payload, headers=headers)

    assert second.json() == first.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    assert await count(session_factory, OrderModel) == 1
    assert await count(session_factory, OutboxEventModel) == 1


async def test_concurrent_requests_with_same_key_create_exactly_one_order(client, session_factory):
    payload = body()
    headers = {"Idempotency-Key": "same-key"}

    responses = await asyncio.gather(
        *(client.post("/orders", json=payload, headers=headers) for _ in range(5))
    )

    assert {r.status_code for r in responses} == {201}
    assert len({r.json()["id"] for r in responses}) == 1
    assert sum(1 for r in responses if r.headers.get("Idempotent-Replayed") == "true") == 4
    assert await count(session_factory, OrderModel) == 1
    assert await count(session_factory, OutboxEventModel) == 1


async def test_same_key_with_different_body_is_rejected_and_saves_nothing_new(
    client, session_factory
):
    headers = {"Idempotency-Key": "k1"}
    await client.post("/orders", json=body(), headers=headers)

    response = await client.post("/orders", json=body(), headers=headers)

    assert response.status_code == 422
    assert await count(session_factory, OrderModel) == 1
