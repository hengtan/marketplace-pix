from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest

from inventory.interface.api import create_app
from tests.auth import SECRET, as_user
from tests.fakes import FakeDatabase, FakeUow

SHOP_A, SHOP_B = uuid4(), uuid4()
PUBLIC_SHAPE = {"product_id", "available"}


@pytest.fixture
def db() -> FakeDatabase:
    database = FakeDatabase()
    ids = database.seed(a=10, b=20, orphan=5)
    database.stocks[ids["a"]].merchant_id = SHOP_A
    database.stocks[ids["a"]].reserved = 4
    database.stocks[ids["b"]].merchant_id = SHOP_B
    database.stocks[ids["b"]].reserved = 7
    database.stocks[ids["orphan"]].reserved = 1
    database.ids = ids  # type: ignore[attr-defined]
    return database


@pytest.fixture
async def client(db: FakeDatabase):
    app = create_app(uow_factory=lambda: FakeUow(db), internal_secret=SECRET)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def ids(db: FakeDatabase) -> dict[str, UUID]:
    return db.ids  # type: ignore[attr-defined]


async def test_anonymous_readers_only_get_available(client, db) -> None:
    one = (await client.get(f"/stock/{ids(db)['a']}")).json()
    assert set(one) == PUBLIC_SHAPE and one["available"] == 10
    for item in (await client.get("/stock")).json():
        assert set(item) == PUBLIC_SHAPE
    listed = (await client.get(f"/stock?product_ids={ids(db)['a']},{ids(db)['b']}")).json()
    assert all(set(item) == PUBLIC_SHAPE for item in listed)
    unknown = (await client.get(f"/stock/{uuid4()}")).json()
    assert set(unknown) == PUBLIC_SHAPE and unknown["available"] == 0


async def test_forged_identity_headers_do_not_unlock_reserved(client, db) -> None:
    forged = {"x-user-id": str(uuid4()), "x-user-roles": "admin", "x-merchant-id": str(SHOP_A)}
    body = (await client.get(f"/stock/{ids(db)['a']}", headers=forged)).json()
    assert set(body) == PUBLIC_SHAPE


async def test_customers_and_other_merchants_do_not_see_reserved(client, db) -> None:
    customer = as_user(("customer",))
    stranger = as_user(("merchant",), merchant_id=SHOP_B)
    for headers in (customer, stranger):
        body = (await client.get(f"/stock/{ids(db)['a']}", headers=headers)).json()
        assert set(body) == PUBLIC_SHAPE


async def test_the_owner_merchant_sees_reserved_of_its_own_products_only(client, db) -> None:
    seller_a = as_user(("merchant",), merchant_id=SHOP_A)
    own = (await client.get(f"/stock/{ids(db)['a']}", headers=seller_a)).json()
    assert own == {"product_id": str(ids(db)["a"]), "available": 10, "reserved": 4}
    other = (await client.get(f"/stock/{ids(db)['b']}", headers=seller_a)).json()
    assert set(other) == PUBLIC_SHAPE
    orphan = (await client.get(f"/stock/{ids(db)['orphan']}", headers=seller_a)).json()
    assert set(orphan) == PUBLIC_SHAPE
    listed = (await client.get("/stock", headers=seller_a)).json()
    by_id = {item["product_id"]: item for item in listed}
    assert by_id[str(ids(db)["a"])]["reserved"] == 4
    assert "reserved" not in by_id[str(ids(db)["b"])]


async def test_admin_sees_reserved_everywhere(client, db) -> None:
    admin = as_user(("admin",))
    for name in ("a", "b", "orphan"):
        body = (await client.get(f"/stock/{ids(db)[name]}", headers=admin)).json()
        assert "reserved" in body


async def test_my_stock_and_put_keep_returning_reserved_to_the_owner(client, db) -> None:
    seller_a = as_user(("merchant",), merchant_id=SHOP_A)
    mine = (await client.get("/stock/mine", headers=seller_a)).json()
    assert [item["reserved"] for item in mine] == [4]
    put = await client.put(f"/stock/{ids(db)['a']}", json={"available": 12}, headers=seller_a)
    assert put.json() == {"product_id": str(ids(db)["a"]), "available": 12, "reserved": 4}
