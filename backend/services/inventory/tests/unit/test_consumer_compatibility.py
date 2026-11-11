from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from marketplace_common.events import golden_payload
from marketplace_common.messaging import IncomingEvent

from inventory.application.common import Outcome
from inventory.application.event_handlers import HandleOrderEvent
from inventory.domain.stock import Stock
from tests.fakes import FakeDatabase, FakeUow

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def incoming(event_type: str, version: int) -> IncomingEvent:
    payload = golden_payload(event_type, version)
    return IncomingEvent(uuid4(), event_type, payload["order_id"], payload, version)


@pytest.mark.parametrize("version", [1, 2])
async def test_inventory_reserves_from_every_order_created_version(version: int) -> None:
    db = FakeDatabase()
    product = UUID(golden_payload("OrderCreated", version)["items"][0]["product_id"])
    db.stocks[product] = Stock(product, 10)
    handler = HandleOrderEvent(lambda: FakeUow(db), timedelta(minutes=35), lambda: NOW)

    assert await handler.handle(incoming("OrderCreated", version)) is Outcome.PROCESSED

    assert (db.stocks[product].available, db.stocks[product].reserved) == (8, 2)


async def test_inventory_registers_stock_from_the_real_product_created_payload() -> None:
    from inventory.application.event_handlers import HandleCatalogEvent

    payload = golden_payload("ProductCreated", 1)
    db = FakeDatabase()
    event = IncomingEvent(uuid4(), "ProductCreated", payload["product_id"], payload, 1)

    assert await HandleCatalogEvent(lambda: FakeUow(db)).handle(event) is Outcome.PROCESSED

    stock = db.stocks[UUID(payload["product_id"])]
    assert (stock.available, str(stock.merchant_id)) == (0, payload["merchant_id"])
