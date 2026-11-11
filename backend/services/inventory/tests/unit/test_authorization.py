from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest

from inventory.interface.api import create_app
from tests.auth import SECRET, as_user
from tests.fakes import FakeDatabase, FakeUow

SHOP_A, SHOP_B = uuid4(), uuid4()


@pytest.fixture
def db() -> FakeDatabase:
    database = FakeDatabase()
    ids = database.seed(a=10, b=20, orphan=5)
    database.stocks[ids["a"]].merchant_id = SHOP_A
    database.stocks[ids["b"]].merchant_id = SHOP_B
    database.ids = ids  # type: ignore[attr-defined]
    return database


@pytest.fixture
async def client(db: FakeDatabase):
    app = create_app(uow_factory=lambda: FakeUow(db), internal_secret=SECRET)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def ids(db: FakeDatabase) -> dict[str, UUID]:
    return db.ids  # type: ignore[attr-defined]


async def test_reading_stock_stays_public(client, db):
    assert (await client.get(f"/stock/{ids(db)['a']}")).status_code == 200
    assert (await client.get("/stock")).status_code == 200


async def test_writing_requires_authentication(client, db):
    response = await client.put(f"/stock/{ids(db)['a']}", json={"available": 1})
    assert response.status_code == 401
    assert db.stocks[ids(db)["a"]].available == 10


async def test_merchant_updates_only_their_own_products(client, db):
    seller_a = as_user(("merchant",), merchant_id=SHOP_A)
    ok = await client.put(f"/stock/{ids(db)['a']}", json={"available": 33}, headers=seller_a)
    assert ok.status_code == 200 and ok.json()["available"] == 33
    cross = await client.put(f"/stock/{ids(db)['b']}", json={"available": 0}, headers=seller_a)
    assert cross.status_code == 403
    assert db.stocks[ids(db)["b"]].available == 20


async def test_merchant_cannot_claim_unowned_or_unknown_products(client, db):
    seller_a = as_user(("merchant",), merchant_id=SHOP_A)
    orphan = await client.put(
        f"/stock/{ids(db)['orphan']}", json={"available": 1}, headers=seller_a
    )
    brand_new = await client.put(f"/stock/{uuid4()}", json={"available": 1}, headers=seller_a)
    assert orphan.status_code == brand_new.status_code == 403
    assert db.stocks[ids(db)["orphan"]].available == 5


async def test_customer_cannot_write_and_admin_can_write_anything(client, db):
    customer = as_user(("customer",))
    assert (
        await client.put(f"/stock/{ids(db)['a']}", json={"available": 1}, headers=customer)
    ).status_code == 403
    admin = as_user(("admin",))
    assert (
        await client.put(f"/stock/{ids(db)['b']}", json={"available": 7}, headers=admin)
    ).status_code == 200


async def test_my_stock_lists_only_the_merchants_products(client, db):
    seller_a = as_user(("merchant",), merchant_id=SHOP_A)
    mine = (await client.get("/stock/mine", headers=seller_a)).json()
    assert [s["product_id"] for s in mine] == [str(ids(db)["a"])]
    assert (await client.get("/stock/mine")).status_code == 401
    assert (await client.get("/stock/mine", headers=as_user(("customer",)))).status_code == 403


async def test_forged_merchant_header_does_not_grant_access(client, db):
    seller_a = as_user(("merchant",), merchant_id=SHOP_A)
    forged = {**seller_a, "x-merchant-id": str(SHOP_B)}
    response = await client.put(f"/stock/{ids(db)['b']}", json={"available": 0}, headers=forged)
    assert response.status_code == 401
