from uuid import uuid4

import httpx
import pytest

from ordering.interface.api import create_app
from tests.fakes import FakeDatabase, FakeUow


@pytest.fixture
def db():
    return FakeDatabase()


@pytest.fixture
async def client(db):
    app = create_app(uow_factory=lambda: FakeUow(db))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def body(quantity=2):
    return {
        "customer_id": str(uuid4()),
        "items": [{"product_id": str(uuid4()), "quantity": quantity, "unit_price_cents": 1990}],
    }


async def test_post_creates_order_and_get_returns_it(client):
    payload = body()
    created = await client.post("/orders", json=payload, headers={"Idempotency-Key": "k1"})
    assert created.status_code == 201

    fetched = await client.get(f"/orders/{created.json()['id']}")
    assert fetched.status_code == 200
    data = fetched.json()
    assert data["status"] == "PENDING"
    assert data["total_cents"] == 3980
    assert data["customer_id"] == payload["customer_id"]


async def test_missing_idempotency_key_is_400(client):
    response = await client.post("/orders", json=body())
    assert response.status_code == 400


async def test_replay_returns_same_id_and_marks_header(client, db):
    payload = body()
    headers = {"Idempotency-Key": "k1"}

    first = await client.post("/orders", json=payload, headers=headers)
    second = await client.post("/orders", json=payload, headers=headers)

    assert second.status_code == 201
    assert second.json() == first.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first.headers
    assert len(db.orders) == 1


async def test_same_key_with_different_body_is_422(client):
    headers = {"Idempotency-Key": "k1"}
    await client.post("/orders", json=body(1), headers=headers)

    response = await client.post("/orders", json=body(5), headers=headers)

    assert response.status_code == 422


async def test_invalid_quantity_is_422(client):
    response = await client.post("/orders", json=body(0), headers={"Idempotency-Key": "k1"})
    assert response.status_code == 422


async def test_empty_items_is_422(client):
    payload = {"customer_id": str(uuid4()), "items": []}
    response = await client.post("/orders", json=payload, headers={"Idempotency-Key": "k1"})
    assert response.status_code == 422


async def test_unknown_order_is_404(client):
    assert (await client.get(f"/orders/{uuid4()}")).status_code == 404


async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
