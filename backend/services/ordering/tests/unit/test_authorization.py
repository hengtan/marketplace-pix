from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest

from ordering.interface.api import create_app
from tests.auth import SECRET, as_user
from tests.fakes import FakeCatalog, FakeDatabase, FakeUow, merchant_of

PRODUCT_A = uuid4()
PRODUCT_B = uuid4()


@pytest.fixture
def db() -> FakeDatabase:
    return FakeDatabase()


@pytest.fixture
async def client(db: FakeDatabase):
    app = create_app(
        uow_factory=lambda: FakeUow(db),
        catalog=FakeCatalog({PRODUCT_A: 1000, PRODUCT_B: 2000}),
        internal_secret=SECRET,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


def payload(product: UUID = PRODUCT_A, customer_id: UUID | None = None) -> dict[str, object]:
    body: dict[str, object] = {
        "customer_name": "Maria Souza",
        "customer_email": "maria@example.com",
        "items": [{"product_id": str(product), "quantity": 1}],
    }
    if customer_id is not None:
        body["customer_id"] = str(customer_id)
    return body


async def place(client: httpx.AsyncClient, headers: dict[str, str], key: str, **kw) -> str:
    response = await client.post(
        "/orders", json=payload(**kw), headers={**headers, "Idempotency-Key": key}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_authenticated_order_belongs_to_the_token_subject_not_the_body(client) -> None:
    alice = uuid4()
    order_id = await place(client, as_user(user_id=alice), "k1")
    data = (await client.get(f"/orders/{order_id}", headers=as_user(user_id=alice))).json()
    assert data["customer_id"] == str(alice)


async def test_customer_id_in_body_must_match_the_token(client) -> None:
    response = await client.post(
        "/orders",
        json=payload(customer_id=uuid4()),
        headers={**as_user(), "Idempotency-Key": "k1"},
    )
    assert response.status_code == 403


async def test_bola_user_b_cannot_read_user_a_order(client) -> None:
    alice, bob = uuid4(), uuid4()
    order_id = await place(client, as_user(user_id=alice), "k1")
    assert (
        await client.get(f"/orders/{order_id}", headers=as_user(user_id=alice))
    ).status_code == 200
    stolen = await client.get(f"/orders/{order_id}", headers=as_user(user_id=bob))
    assert stolen.status_code == 404
    assert stolen.json() == {"detail": "order not found"}
    assert (await client.get(f"/orders/{order_id}")).status_code == 404


async def test_a_nonexistent_order_looks_the_same_as_someone_elses(client) -> None:
    alice = uuid4()
    order_id = await place(client, as_user(user_id=alice), "k1")
    other = await client.get(f"/orders/{order_id}", headers=as_user())
    missing = await client.get(f"/orders/{uuid4()}", headers=as_user())
    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()


async def test_a_forged_identity_header_is_not_trusted(client) -> None:
    alice = uuid4()
    order_id = await place(client, as_user(user_id=alice), "k1")
    forged = {"x-user-id": str(alice), "x-user-roles": "admin"}
    assert (await client.get(f"/orders/{order_id}", headers=forged)).status_code == 404
    wrong_secret = as_user(user_id=alice, secret="other-secret")
    assert (await client.get(f"/orders/{order_id}", headers=wrong_secret)).status_code == 404


async def test_admin_can_read_any_order_but_a_merchant_cannot(client) -> None:
    order_id = await place(client, as_user(), "k1")
    admin = as_user(("admin",))
    assert (await client.get(f"/orders/{order_id}", headers=admin)).status_code == 200
    seller = as_user(("merchant",), merchant_id=merchant_of(PRODUCT_A))
    assert (await client.get(f"/orders/{order_id}", headers=seller)).status_code == 404


async def test_list_returns_only_my_orders_and_ignores_someone_elses_customer_id(client) -> None:
    alice, bob = uuid4(), uuid4()
    await place(client, as_user(user_id=alice), "a1")
    await place(client, as_user(user_id=alice), "a2")
    await place(client, as_user(user_id=bob), "b1")
    mine = (await client.get("/orders", headers=as_user(user_id=alice))).json()
    assert mine["total"] == 2
    assert {o["customer_id"] for o in mine["items"]} == {str(alice)}
    snoop = await client.get(f"/orders?customer_id={alice}", headers=as_user(user_id=bob))
    assert snoop.status_code == 403
    admin = await client.get(f"/orders?customer_id={alice}", headers=as_user(("admin",)))
    assert admin.json()["total"] == 2


async def test_guest_checkout_still_works_and_stays_private_from_account_listings(client) -> None:
    guest = uuid4()
    order_id = await place(client, {}, "g1", customer_id=guest)
    assert (await client.get(f"/orders/{order_id}")).status_code == 200
    listed = (await client.get(f"/orders?customer_id={guest}")).json()
    assert listed["total"] == 1
    victim_view = await client.get("/orders", headers=as_user(user_id=guest))
    assert victim_view.json()["total"] == 0


async def test_guest_cannot_enumerate_a_registered_users_orders_by_customer_id(client) -> None:
    alice = uuid4()
    await place(client, as_user(user_id=alice), "a1")
    assert (await client.get(f"/orders?customer_id={alice}")).json()["total"] == 0


async def test_guest_checkout_needs_a_customer_id(client) -> None:
    response = await client.post("/orders", json=payload(), headers={"Idempotency-Key": "g1"})
    assert response.status_code == 422


async def test_idempotency_key_cannot_be_replayed_by_another_user(client) -> None:
    alice_order = await place(client, as_user(), "same-key")
    other = await client.post(
        "/orders", json=payload(), headers={**as_user(), "Idempotency-Key": "same-key"}
    )
    assert other.status_code == 422
    assert alice_order not in other.text


async def test_customer_without_create_scope_cannot_order(client) -> None:
    response = await client.post(
        "/orders", json=payload(), headers={**as_user(("unknown",)), "Idempotency-Key": "k"}
    )
    assert response.status_code == 403


async def test_merchant_sees_only_orders_and_items_of_their_own_store(client) -> None:
    shop_a = merchant_of(PRODUCT_A)
    shop_b = merchant_of(PRODUCT_B)
    seller_a = as_user(("merchant",), merchant_id=shop_a)
    seller_b = as_user(("merchant",), merchant_id=shop_b)
    both = {
        "customer_name": "Maria",
        "customer_email": "maria@example.com",
        "items": [
            {"product_id": str(PRODUCT_A), "quantity": 1},
            {"product_id": str(PRODUCT_B), "quantity": 2},
        ],
    }
    created = await client.post(
        "/orders", json=both, headers={**as_user(), "Idempotency-Key": "m1"}
    )
    assert created.status_code == 201
    await place(client, as_user(), "m2", product=PRODUCT_B)

    a = (await client.get("/orders/merchant", headers=seller_a)).json()
    b = (await client.get("/orders/merchant", headers=seller_b)).json()
    assert a["total"] == 1 and b["total"] == 2
    assert all(i["merchant_id"] == str(shop_a) for o in a["items"] for i in o["items"])
    assert a["items"][0]["subtotal_cents"] == 1000
    assert "customer_email" not in a["items"][0]
    cross = await client.get(f"/orders/merchant?merchant_id={shop_b}", headers=seller_a)
    assert cross.status_code == 403


async def test_merchant_listing_requires_merchant_privileges(client) -> None:
    assert (await client.get("/orders/merchant")).status_code == 401
    assert (await client.get("/orders/merchant", headers=as_user())).status_code == 403
    no_store = as_user(("merchant",))
    assert (await client.get("/orders/merchant", headers=no_store)).status_code == 403
