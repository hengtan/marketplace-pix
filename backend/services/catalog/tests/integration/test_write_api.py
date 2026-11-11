from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select, text

from catalog.application.commands import ManageProducts
from catalog.infrastructure.db.models import OutboxEventModel
from catalog.infrastructure.db.repository import build_reader_factory
from catalog.infrastructure.db.uow import SqlAlchemyUnitOfWork
from catalog.interface.api import create_app
from catalog.seed_data import merchant_id, product_id
from tests.auth import SECRET, as_user

FONE = product_id("fone-bluetooth-nova")
AURORA = merchant_id("aurora-tech")
CASA = merchant_id("casa-lume")


@pytest.fixture
async def writer(seeded, engine):
    async with engine.begin() as conn:
        await conn.execute(text("truncate outbox_events"))
    app = create_app(
        reader_factory=build_reader_factory(seeded),
        manage_products=ManageProducts(lambda: SqlAlchemyUnitOfWork(seeded)),
        internal_secret=SECRET,
        cache_max_age=0,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        yield http


async def outbox(session_factory) -> list[OutboxEventModel]:
    async with session_factory() as session:
        rows = await session.scalars(select(OutboxEventModel).order_by(OutboxEventModel.created_at))
        return list(rows)


async def test_owner_changes_the_price_and_the_event_is_in_the_outbox(writer, seeded) -> None:
    response = await writer.patch(
        f"/products/{FONE}",
        json={"price_cents": 29990},
        headers=as_user(("merchant",), None, AURORA),
    )
    assert response.status_code == 200
    assert response.json()["price_cents"] == 29990
    assert (await writer.get(f"/products/{FONE}")).json()["price_cents"] == 29990
    (row,) = await outbox(seeded)
    assert row.topic == "catalog.events"
    assert row.type == "ProductPriceChanged"
    assert row.key == str(FONE)
    assert row.payload["old_price_cents"] == 34990
    assert row.payload["new_price_cents"] == 29990
    assert row.payload["schema_version"] == 1
    assert row.published_at is None


async def test_another_merchant_cannot_change_the_product(writer, seeded) -> None:
    response = await writer.patch(
        f"/products/{FONE}", json={"price_cents": 1}, headers=as_user(("merchant",), None, CASA)
    )
    assert response.status_code == 403
    assert (await writer.get(f"/products/{FONE}")).json()["price_cents"] == 34990
    assert await outbox(seeded) == []


async def test_customer_and_anonymous_cannot_write(writer) -> None:
    body = {"price_cents": 1}
    assert (await writer.patch(f"/products/{FONE}", json=body)).status_code == 401
    forged = {"x-user-id": "00000000-0000-4000-8000-000000000001", "x-user-roles": "admin"}
    assert (await writer.patch(f"/products/{FONE}", json=body, headers=forged)).status_code == 401
    customer = as_user(("customer",))
    assert (await writer.patch(f"/products/{FONE}", json=body, headers=customer)).status_code == 403


async def test_admin_can_change_any_product(writer) -> None:
    response = await writer.patch(
        f"/products/{FONE}", json={"name": "Fone Nova ANC 2"}, headers=as_user(("admin",))
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Fone Nova ANC 2"


async def test_a_patch_that_changes_nothing_emits_nothing(writer, seeded) -> None:
    response = await writer.patch(
        f"/products/{FONE}",
        json={"price_cents": 34990},
        headers=as_user(("merchant",), None, AURORA),
    )
    assert response.status_code == 200
    assert await outbox(seeded) == []


async def test_invalid_patches_are_rejected_with_422(writer, seeded) -> None:
    headers = as_user(("merchant",), None, AURORA)
    for body in ({"price_cents": 0}, {"category": "nao-existe"}, {"rating": 5}, {}):
        response = await writer.patch(f"/products/{FONE}", json=body, headers=headers)
        assert response.status_code == 422, body
        assert isinstance(response.json()["detail"], str)
    assert await outbox(seeded) == []


async def test_unknown_product_is_404(writer) -> None:
    response = await writer.patch(
        "/products/00000000-0000-4000-8000-0000000000aa",
        json={"price_cents": 5},
        headers=as_user(("admin",)),
    )
    assert response.status_code == 404


async def test_merchant_creates_a_product_in_its_own_store(writer, seeded) -> None:
    response = await writer.post(
        "/products",
        json={
            "name": "Fone Aurora Mini",
            "description": "Fone compacto",
            "price_cents": 15990,
            "category": "tecnologia",
            "tags": ["audio"],
        },
        headers=as_user(("merchant",), None, AURORA),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["merchant"]["slug"] == "aurora-tech"
    assert body["slug"] == "fone-aurora-mini"
    (row,) = await outbox(seeded)
    assert row.type == "ProductCreated"
    assert row.key == body["id"] == row.payload["product_id"]
    assert (await writer.get(f"/products/{body['id']}")).status_code == 200


async def test_duplicate_slug_is_a_conflict(writer, seeded) -> None:
    response = await writer.post(
        "/products",
        json={
            "name": "Outro",
            "slug": "fone-bluetooth-nova",
            "description": "x",
            "price_cents": 100,
            "category": "tecnologia",
        },
        headers=as_user(("merchant",), None, AURORA),
    )
    assert response.status_code == 409
    assert await outbox(seeded) == []


async def test_a_merchant_cannot_create_for_another_store(writer) -> None:
    response = await writer.post(
        "/products",
        json={
            "name": "Invasor",
            "description": "x",
            "price_cents": 100,
            "category": "casa",
            "merchant_id": str(CASA),
        },
        headers=as_user(("merchant",), None, AURORA),
    )
    assert response.status_code == 403


async def test_deactivating_hides_the_product_and_emits_the_event(writer, seeded) -> None:
    headers = as_user(("merchant",), None, AURORA)
    assert (await writer.delete(f"/products/{FONE}", headers=headers)).status_code == 204
    assert (await writer.get(f"/products/{FONE}")).status_code == 404
    listing = (await writer.get("/products", params={"page_size": 48})).json()
    assert FONE.hex not in {i["id"].replace("-", "") for i in listing["items"]}
    assert listing["total"] == 23
    by_ids = (await writer.get("/products/by-ids", params={"ids": str(FONE)})).json()
    assert by_ids["items"] == []
    (row,) = await outbox(seeded)
    assert row.type == "ProductDeactivated"
    assert (await writer.delete(f"/products/{FONE}", headers=headers)).status_code == 204
    assert len(await outbox(seeded)) == 1


async def test_owner_reactivates_a_product_and_it_returns_to_the_shelf(writer, seeded) -> None:
    headers = as_user(("merchant",), None, AURORA)
    await writer.delete(f"/products/{FONE}", headers=headers)
    response = await writer.post(f"/products/{FONE}/reactivate", headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] == str(FONE)
    assert (await writer.get(f"/products/{FONE}")).status_code == 200
    listing = (await writer.get("/products", params={"page_size": 48})).json()
    assert listing["total"] == 24
    types = [row.type for row in await outbox(seeded)]
    assert types == ["ProductDeactivated", "ProductCreated"]


async def test_reactivating_an_active_product_is_a_quiet_no_op(writer, seeded) -> None:
    headers = as_user(("merchant",), None, AURORA)
    assert (await writer.post(f"/products/{FONE}/reactivate", headers=headers)).status_code == 200
    assert await outbox(seeded) == []


async def test_another_merchant_cannot_reactivate_and_unknown_ids_are_404(writer) -> None:
    owner = as_user(("merchant",), None, AURORA)
    await writer.delete(f"/products/{FONE}", headers=owner)
    other = as_user(("merchant",), None, CASA)
    assert (await writer.post(f"/products/{FONE}/reactivate", headers=other)).status_code == 403
    missing = "00000000-0000-4000-8000-000000000000"
    assert (await writer.post(f"/products/{missing}/reactivate", headers=owner)).status_code == 404


async def test_owner_lists_every_own_product_including_deactivated_ones(writer) -> None:
    owner = as_user(("merchant",), None, AURORA)
    await writer.delete(f"/products/{FONE}", headers=owner)

    response = await writer.get("/products/mine", headers=owner)

    assert response.status_code == 200
    items = response.json()["items"]
    assert {i["merchant"]["id"] for i in items} == {str(AURORA)}
    by_id = {i["id"]: i for i in items}
    assert by_id[str(FONE)]["active"] is False
    assert any(i["active"] for i in items)
    assert response.headers["cache-control"] == "no-store"


async def test_a_merchant_never_sees_another_merchants_products_in_the_owner_list(writer) -> None:
    items = (await writer.get("/products/mine", headers=as_user(("merchant",), None, CASA))).json()[
        "items"
    ]
    assert items
    assert {i["merchant"]["id"] for i in items} == {str(CASA)}


async def test_the_owner_list_requires_a_write_scope(writer) -> None:
    assert (await writer.get("/products/mine")).status_code == 401
    customer = as_user(("customer",), None, None)
    assert (await writer.get("/products/mine", headers=customer)).status_code == 403


async def test_an_admin_must_say_which_store_to_list(writer) -> None:
    admin = as_user(("admin",), None, None)
    assert (await writer.get("/products/mine", headers=admin)).status_code == 422
    listed = await writer.get("/products/mine", params={"merchant_id": str(CASA)}, headers=admin)
    assert listed.status_code == 200
    assert {i["merchant"]["id"] for i in listed.json()["items"]} == {str(CASA)}
