from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
import pytest

from inventory.interface.api import create_app
from inventory.seed import PRODUCT_SLUGS, initial_stock, product_id_for
from tests.auth import SECRET, as_user
from tests.fakes import FakeDatabase, FakeUow


@pytest.fixture
def db():
    database = FakeDatabase()
    database.ids = database.seed(a=10, b=3)
    return database


@pytest.fixture
async def client(db):
    app = create_app(uow_factory=lambda: FakeUow(db), internal_secret=SECRET)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers=as_user(("admin",))
    ) as client:
        yield client


async def test_get_stock_for_several_products(client, db):
    ids = f"{db.ids['a']},{db.ids['b']}"

    response = await client.get(f"/stock?product_ids={ids}")

    assert response.status_code == 200
    assert response.json() == [
        {"product_id": str(db.ids["a"]), "available": 10, "reserved": 0},
        {"product_id": str(db.ids["b"]), "available": 3, "reserved": 0},
    ]


async def test_unknown_product_has_zero_stock(client):
    unknown = uuid4()

    response = await client.get(f"/stock/{unknown}")

    assert response.status_code == 200
    assert response.json() == {"product_id": str(unknown), "available": 0, "reserved": 0}


async def test_list_without_filter_returns_everything(client, db):
    response = await client.get("/stock")

    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_invalid_product_ids_are_rejected(client):
    response = await client.get("/stock?product_ids=abc")

    assert response.status_code == 422
    assert "detail" in response.json()


async def test_put_sets_available_and_keeps_reserved(client, db):
    db.stocks[db.ids["a"]].reserved = 2

    response = await client.put(f"/stock/{db.ids['a']}", json={"available": 40})

    assert response.status_code == 200
    assert response.json() == {"product_id": str(db.ids["a"]), "available": 40, "reserved": 2}
    assert db.stocks[db.ids["a"]].available == 40


async def test_put_rejects_negative_quantity(client, db):
    response = await client.put(f"/stock/{db.ids['a']}", json={"available": -1})

    assert response.status_code == 422
    assert db.stocks[db.ids["a"]].available == 10


async def test_health_and_ready(client):
    assert (await client.get("/health")).json() == {"status": "ok"}
    assert (await client.get("/ready")).status_code == 200


def test_seed_matches_the_contract():
    stock = initial_stock()

    assert len(PRODUCT_SLUGS) == len(stock) == 24
    assert product_id_for("smartwatch-orbit") == uuid5(
        NAMESPACE_URL, "marketplace-pix:product:smartwatch-orbit"
    )
    assert stock[product_id_for("relogio-gps-trail")] == 3
    assert stock[product_id_for("smartwatch-orbit")] == 5
    assert sorted(stock.values()).count(25) == 22
