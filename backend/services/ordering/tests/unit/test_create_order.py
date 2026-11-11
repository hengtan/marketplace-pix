from uuid import uuid4

import pytest

from ordering.application.create_order import CreateOrder, CreateOrderCommand, CreateOrderItem
from ordering.application.errors import CatalogUnavailable, IdempotencyKeyReused, UnknownProduct
from ordering.domain.events import OrderCreated
from tests.fakes import FakeCatalog, FakeDatabase, FakeUow, merchant_of

PRODUCT_A, PRODUCT_B = uuid4(), uuid4()


def command(customer_id=None, qty=2) -> CreateOrderCommand:
    return CreateOrderCommand(
        customer_id=customer_id or uuid4(),
        customer_name="Maria Souza",
        customer_email="maria@example.com",
        items=[CreateOrderItem(PRODUCT_A, qty), CreateOrderItem(PRODUCT_B, 1)],
    )


@pytest.fixture
def catalog():
    return FakeCatalog({PRODUCT_A: 1990, PRODUCT_B: 500})


@pytest.fixture
def db():
    return FakeDatabase()


async def test_prices_and_merchants_come_from_the_catalog(db, catalog):
    result = await CreateOrder(lambda: FakeUow(db), catalog).execute(command())

    assert not result.replayed
    order = db.orders[result.order_id]
    assert order.total.cents == 4480
    assert order.items[0].merchant_id == merchant_of(PRODUCT_A)
    (event,) = db.events
    assert isinstance(event, OrderCreated)
    assert event.customer_email == "maria@example.com"
    assert [i.unit_price_cents for i in event.items] == [1990, 500]


async def test_duplicate_product_lines_are_merged(db, catalog):
    cmd = CreateOrderCommand(
        uuid4(),
        "Maria",
        "maria@example.com",
        [CreateOrderItem(PRODUCT_A, 1), CreateOrderItem(PRODUCT_A, 2)],
    )

    result = await CreateOrder(lambda: FakeUow(db), catalog).execute(cmd)

    (item,) = db.orders[result.order_id].items
    assert item.quantity == 3


async def test_unknown_product_is_rejected_and_nothing_is_saved(db, catalog):
    catalog.unknown.add(PRODUCT_B)

    with pytest.raises(UnknownProduct):
        await CreateOrder(lambda: FakeUow(db), catalog).execute(command())

    assert db.orders == {} and db.events == []


async def test_catalog_down_fails_without_saving(db, catalog):
    catalog.fail = True

    with pytest.raises(CatalogUnavailable):
        await CreateOrder(lambda: FakeUow(db), catalog).execute(command())

    assert db.orders == {}


async def test_same_key_and_same_body_returns_the_same_order_without_duplicating(db, catalog):
    use_case = CreateOrder(lambda: FakeUow(db), catalog)
    cmd = command()

    first = await use_case.execute(cmd, "key-1")
    second = await use_case.execute(cmd, "key-1")

    assert second.order_id == first.order_id
    assert second.replayed and not first.replayed
    assert len(db.orders) == 1 and len(db.events) == 1


async def test_same_key_with_different_body_is_rejected(db, catalog):
    use_case = CreateOrder(lambda: FakeUow(db), catalog)
    customer = uuid4()

    await use_case.execute(command(customer, qty=2), "key-1")
    with pytest.raises(IdempotencyKeyReused):
        await use_case.execute(command(customer, qty=3), "key-1")

    assert len(db.orders) == 1


async def test_different_keys_create_different_orders(db, catalog):
    use_case = CreateOrder(lambda: FakeUow(db), catalog)
    cmd = command()

    await use_case.execute(cmd, "key-1")
    await use_case.execute(cmd, "key-2")

    assert len(db.orders) == 2
