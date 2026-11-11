from uuid import uuid4

import httpx
import pytest

from inventory.application.reserve_stock import ReserveStock
from inventory.infrastructure.db.models import StockModel
from inventory.interface.api import create_app
from inventory.seed import initial_stock, product_id_for, seed
from tests.integration.helpers import count, items, stock_levels


@pytest.fixture
async def client(uow_factory):
    app = create_app(uow_factory=uow_factory)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_seed_is_idempotent_and_never_resets_existing_stock(session_factory, uow_factory):
    assert await seed(session_factory) == 24
    watch = product_id_for("smartwatch-orbit")
    await ReserveStock(uow_factory).execute(uuid4(), items((watch, 2)))

    assert await seed(session_factory) == 0

    assert await count(session_factory, StockModel) == len(initial_stock())
    assert await stock_levels(session_factory, watch) == (3, 2)
    assert await stock_levels(session_factory, product_id_for("relogio-gps-trail")) == (3, 0)
    assert await stock_levels(session_factory, product_id_for("fone-bluetooth-nova")) == (25, 0)


async def test_put_then_get_stock_through_the_api(client, session_factory):
    product = product_id_for("mouse-glide-pro")

    put = await client.put(f"/stock/{product}", json={"available": 12})
    got = await client.get(f"/stock/{product}")
    listed = await client.get(f"/stock?product_ids={product},{product_id_for('x')}")

    assert put.status_code == got.status_code == 200
    assert got.json() == {"product_id": str(product), "available": 12, "reserved": 0}
    assert [s["available"] for s in listed.json()] == [12, 0]


async def test_api_reflects_reservations(client, session_factory, uow_factory):
    product = product_id_for("mouse-glide-pro")
    await client.put(f"/stock/{product}", json={"available": 5})
    await ReserveStock(uow_factory).execute(uuid4(), items((product, 2)))

    response = await client.get(f"/stock/{product}")

    assert response.json() == {"product_id": str(product), "available": 3, "reserved": 2}


async def test_ready_checks_the_database(client):
    assert (await client.get("/ready")).status_code == 200
