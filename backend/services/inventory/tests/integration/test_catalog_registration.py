from uuid import uuid4

from marketplace_common.messaging import IncomingEvent
from sqlalchemy import select

from inventory.application.event_handlers import HandleCatalogEvent
from inventory.infrastructure.db.models import StockModel


def created(product_id, merchant_id) -> IncomingEvent:
    return IncomingEvent(
        uuid4(),
        "ProductCreated",
        str(product_id),
        {"product_id": str(product_id), "merchant_id": str(merchant_id)},
    )


def deactivated(product_id, merchant_id) -> IncomingEvent:
    return IncomingEvent(
        uuid4(),
        "ProductDeactivated",
        str(product_id),
        {"product_id": str(product_id), "merchant_id": str(merchant_id)},
    )


async def row(session_factory, product_id) -> StockModel:
    async with session_factory() as session:
        found = await session.scalar(select(StockModel).where(StockModel.product_id == product_id))
        assert found is not None
        return found


async def listed(uow_factory, merchant_id) -> set:
    async with uow_factory() as uow:
        return {s.product_id for s in await uow.stocks.list_by_merchant(merchant_id, 100)}


async def test_adopting_an_unowned_stock_row_is_persisted_in_postgres(
    uow_factory, session_factory
) -> None:
    product, merchant = uuid4(), uuid4()
    async with session_factory() as session:
        session.add(StockModel(product_id=product, available=7, reserved=0))
        await session.commit()

    await HandleCatalogEvent(uow_factory).handle(created(product, merchant))

    stored = await row(session_factory, product)
    assert (stored.available, stored.merchant_id) == (7, merchant)


async def test_an_existing_owner_is_never_replaced_in_postgres(
    uow_factory, session_factory
) -> None:
    product, owner = uuid4(), uuid4()
    async with session_factory() as session:
        session.add(StockModel(product_id=product, available=3, reserved=0, merchant_id=owner))
        await session.commit()

    await HandleCatalogEvent(uow_factory).handle(created(product, uuid4()))

    assert (await row(session_factory, product)).merchant_id == owner


async def test_a_deactivated_product_leaves_the_merchant_stock_list_and_returns_on_reactivation(
    uow_factory, session_factory
) -> None:
    product, merchant = uuid4(), uuid4()
    handler = HandleCatalogEvent(uow_factory)
    await handler.handle(created(product, merchant))
    assert await listed(uow_factory, merchant) == {product}

    await handler.handle(deactivated(product, merchant))
    assert await listed(uow_factory, merchant) == set()
    stored = await row(session_factory, product)
    assert stored.available == 0

    await handler.handle(created(product, merchant))
    assert await listed(uow_factory, merchant) == {product}
