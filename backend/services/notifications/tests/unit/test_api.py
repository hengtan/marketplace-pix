from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import httpx
import pytest

from notifications.application.handle_event import HandleEvent
from notifications.infrastructure.rendering.jinja import JinjaEmailRenderer
from notifications.interface.api import create_app
from tests.fakes import FakeDatabase, FakeQueue, FakeUow
from tests.helpers import CUSTOMER_ID, NOW, order_cancelled, order_created, payment_created


@pytest.fixture
async def seeded() -> tuple[FakeDatabase, UUID]:
    db = FakeDatabase()
    handler = HandleEvent(lambda: FakeUow(db), FakeQueue(), clock=lambda: NOW)
    created = order_created()
    order_id = UUID(created.payload["order_id"])
    await handler.handle(created)
    await handler.handle(payment_created(order_id))
    await handler.handle(order_cancelled(order_id, "out of stock"))
    await handler.handle(order_created(customer_id=uuid4()))
    return db, order_id


@pytest.fixture
async def client(seeded: tuple[FakeDatabase, UUID]) -> AsyncIterator[httpx.AsyncClient]:
    db, _ = seeded
    app = create_app(uow_factory=lambda: FakeUow(db), renderer=JinjaEmailRenderer())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def test_lists_notifications_of_a_customer_with_the_contract_shape(
    client: httpx.AsyncClient, seeded: tuple[FakeDatabase, UUID]
) -> None:
    response = await client.get("/notifications", params={"customer_id": str(CUSTOMER_ID)})

    assert response.status_code == 200
    body = response.json()
    assert (body["total"], body["page"], body["page_size"]) == (3, 1, 20)
    first = body["items"][0]
    assert set(first) == {"id", "kind", "subject", "status", "order_id", "created_at", "sent_at"}
    assert {item["kind"] for item in body["items"]} == {
        "ORDER_CREATED",
        "PIX_READY",
        "ORDER_CANCELLED",
    }
    assert all(item["status"] == "QUEUED" and item["sent_at"] is None for item in body["items"])
    assert {item["order_id"] for item in body["items"]} == {str(seeded[1])}


async def test_pagination(client: httpx.AsyncClient) -> None:
    response = await client.get("/notifications", params={"page": 2, "page_size": 2})
    body = response.json()
    assert body["total"] == 4 and len(body["items"]) == 2 and body["page"] == 2


async def test_rejects_invalid_pagination(client: httpx.AsyncClient) -> None:
    assert (await client.get("/notifications", params={"page": 0})).status_code == 422
    assert (await client.get("/notifications", params={"page_size": 500})).status_code == 422


async def test_preview_returns_the_rendered_html(client: httpx.AsyncClient) -> None:
    listing = (await client.get("/notifications", params={"customer_id": str(CUSTOMER_ID)})).json()
    cancelled = next(i for i in listing["items"] if i["kind"] == "ORDER_CANCELLED")

    response = await client.get(f"/notifications/{cancelled['id']}/preview")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "estoque insuficiente" in response.text
    assert "<!doctype html>" in response.text


async def test_preview_of_unknown_notification_is_404(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/notifications/{uuid4()}/preview")
    assert response.status_code == 404
    assert response.json() == {"detail": "notification not found"}


async def test_health_and_ready(client: httpx.AsyncClient) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}
    assert (await client.get("/ready")).status_code == 200
