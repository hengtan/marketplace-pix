from uuid import uuid4

import httpx
import pytest

from inventory.application.reserve_stock import ReserveStock
from inventory.infrastructure.db.models import StockModel
from inventory.interface.api import create_app
from inventory.seed import initial_stock, merchant_id_for, product_id_for, seed
from tests.auth import SECRET, as_user
from tests.integration.helpers import count, items, stock_levels


@pytest.fixture
async def client(uow_factory):
    app = create_app(uow_factory=uow_factory, internal_secret=SECRET)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=as_user(("admin",))
    ) as client:
        yield client


@pytest.fixture
async def anonymous(uow_factory):
    app = create_app(uow_factory=uow_factory, internal_secret=SECRET)
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


async def test_the_public_api_hides_reserved_from_everyone_but_the_owner(
    anonymous, session_factory, uow_factory
):
    await seed(session_factory)
    watch = product_id_for("smartwatch-orbit")
    await ReserveStock(uow_factory).execute(uuid4(), items((watch, 2)))
    public = await anonymous.get(f"/stock/{watch}")
    assert public.json() == {"product_id": str(watch), "available": 3}
    owner = as_user(("merchant",), merchant_id=merchant_id_for("aurora-tech"))
    assert (await anonymous.get(f"/stock/{watch}", headers=owner)).json()["reserved"] == 2
    rival = as_user(("merchant",), merchant_id=merchant_id_for("trilha-sports"))
    assert "reserved" not in (await anonymous.get(f"/stock/{watch}", headers=rival)).json()


async def test_ready_checks_the_database(client):
    assert (await client.get("/ready")).status_code == 200


async def test_seed_assigns_owners_and_merchants_cannot_cross_edit(anonymous, session_factory):
    await seed(session_factory)
    aurora = as_user(("merchant",), merchant_id=merchant_id_for("aurora-tech"))
    trilha = as_user(("merchant",), merchant_id=merchant_id_for("trilha-sports"))
    watch = product_id_for("smartwatch-orbit")
    shoes = product_id_for("tenis-corrida-vento")
    plain = anonymous
    mine = (await plain.get("/stock/mine", headers=aurora)).json()
    assert len(mine) == 8 and str(watch) in {s["product_id"] for s in mine}
    assert (
        await plain.put(f"/stock/{watch}", json={"available": 9}, headers=aurora)
    ).status_code == 200
    assert (
        await plain.put(f"/stock/{shoes}", json={"available": 0}, headers=aurora)
    ).status_code == 403
    assert (
        await plain.put(f"/stock/{shoes}", json={"available": 4}, headers=trilha)
    ).status_code == 200
    assert await stock_levels(session_factory, shoes) == (4, 0)
