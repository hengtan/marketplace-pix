from uuid import uuid4

import pytest
from marketplace_common.messaging import IncomingEvent

from inventory.application.common import Outcome
from inventory.application.event_handlers import CATALOG_CONSUMER, HandleCatalogEvent
from inventory.domain.stock import Stock
from tests.fakes import FakeDatabase, FakeUow


@pytest.fixture
def db() -> FakeDatabase:
    return FakeDatabase()


@pytest.fixture
def handler(db: FakeDatabase) -> HandleCatalogEvent:
    return HandleCatalogEvent(lambda: FakeUow(db))


def created(product_id, merchant_id, event_id=None) -> IncomingEvent:
    return IncomingEvent(
        id=event_id or uuid4(),
        type="ProductCreated",
        key=str(product_id),
        payload={
            "product_id": str(product_id),
            "merchant_id": str(merchant_id),
            "slug": "novo",
            "name": "Novo",
            "category": "esporte",
            "price_cents": 1000,
            "currency": "BRL",
        },
    )


async def test_a_new_product_gets_an_empty_stock_row_owned_by_its_merchant(db, handler) -> None:
    product_id, merchant_id = uuid4(), uuid4()
    assert await handler.handle(created(product_id, merchant_id)) is Outcome.PROCESSED
    stock = db.stocks[product_id]
    assert (stock.available, stock.reserved, stock.merchant_id) == (0, 0, merchant_id)


async def test_a_redelivered_event_is_a_duplicate(db, handler) -> None:
    product_id, merchant_id, event_id = uuid4(), uuid4(), uuid4()
    await handler.handle(created(product_id, merchant_id, event_id))
    assert await handler.handle(created(product_id, merchant_id, event_id)) is Outcome.DUPLICATE
    assert len(db.stocks) == 1


async def test_an_existing_stock_keeps_its_quantity(db, handler) -> None:
    product_id, merchant_id = uuid4(), uuid4()
    db.stocks[product_id] = Stock(product_id, 25, merchant_id=merchant_id)
    await handler.handle(created(product_id, merchant_id))
    assert db.stocks[product_id].available == 25


async def test_an_existing_stock_without_owner_is_adopted_by_the_merchant(db, handler) -> None:
    product_id, merchant_id = uuid4(), uuid4()
    db.stocks[product_id] = Stock(product_id, 7)
    await handler.handle(created(product_id, merchant_id))
    stock = db.stocks[product_id]
    assert (stock.available, stock.merchant_id) == (7, merchant_id)


async def test_an_existing_owner_is_never_replaced(db, handler) -> None:
    product_id, owner = uuid4(), uuid4()
    db.stocks[product_id] = Stock(product_id, 7, merchant_id=owner)
    await handler.handle(created(product_id, uuid4()))
    assert db.stocks[product_id].merchant_id == owner


@pytest.mark.parametrize("payload", [{}, {"product_id": "nao-e-uuid", "merchant_id": "x"}])
async def test_a_malformed_event_is_ignored_instead_of_blocking_the_partition(
    db, handler, payload
) -> None:
    event = IncomingEvent(id=uuid4(), type="ProductCreated", key="k", payload=payload)
    assert await handler.handle(event) is Outcome.IGNORED
    assert db.stocks == {}


async def test_other_catalog_events_do_not_touch_stock(db, handler) -> None:
    event = IncomingEvent(
        id=uuid4(), type="ProductPriceChanged", key="k", payload={"product_id": str(uuid4())}
    )
    assert await handler.handle(event) is Outcome.IGNORED
    assert db.stocks == {}


def test_the_consumer_group_name_is_stable() -> None:
    assert CATALOG_CONSUMER == "inventory-catalog"


def deactivated(product_id, merchant_id) -> IncomingEvent:
    return IncomingEvent(
        id=uuid4(),
        type="ProductDeactivated",
        key=str(product_id),
        payload={"product_id": str(product_id), "merchant_id": str(merchant_id)},
    )


async def test_a_deactivated_product_leaves_the_merchant_list_but_keeps_its_quantity(
    db, handler
) -> None:
    product_id, merchant_id = uuid4(), uuid4()
    db.stocks[product_id] = Stock(product_id, 12, merchant_id=merchant_id)

    assert await handler.handle(deactivated(product_id, merchant_id)) is Outcome.PROCESSED

    async with FakeUow(db) as uow:
        assert await uow.stocks.list_by_merchant(merchant_id, 10) == []
    assert db.stocks[product_id].available == 12


async def test_reactivation_brings_the_stock_back_without_touching_the_quantity(
    db, handler
) -> None:
    product_id, merchant_id = uuid4(), uuid4()
    db.stocks[product_id] = Stock(product_id, 12, merchant_id=merchant_id, active=False)

    await handler.handle(created(product_id, merchant_id))

    assert (db.stocks[product_id].active, db.stocks[product_id].available) == (True, 12)


async def test_deactivating_an_unknown_product_is_ignored(db, handler) -> None:
    assert await handler.handle(deactivated(uuid4(), uuid4())) is Outcome.IGNORED
