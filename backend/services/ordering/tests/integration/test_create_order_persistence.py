from uuid import uuid4

import pytest
from sqlalchemy import func, select

from ordering.application.create_order import CreateOrder, CreateOrderCommand, CreateOrderItem
from ordering.domain.money import Money
from ordering.domain.order import Order, OrderItem, OrderStatus
from ordering.infrastructure.db.models import OrderModel, OutboxEventModel
from tests.fakes import FakeCatalog, merchant_of

A, B = uuid4(), uuid4()


def command() -> CreateOrderCommand:
    return CreateOrderCommand(
        customer_id=uuid4(),
        customer_name="Maria Souza",
        customer_email="maria@example.com",
        items=[CreateOrderItem(A, 2), CreateOrderItem(B, 1)],
    )


async def test_order_and_outbox_event_are_saved_together(uow_factory, session_factory):
    catalog = FakeCatalog({A: 1990, B: 500})
    order_id = (await CreateOrder(uow_factory, catalog).execute(command())).order_id

    async with uow_factory() as uow:
        order = await uow.orders.get(order_id)
    assert order is not None
    assert order.status is OrderStatus.PENDING
    assert order.total == Money(4480)
    assert order.customer_email == "maria@example.com"
    assert order.created_at is not None
    assert [i.merchant_id for i in order.items] == [merchant_of(A), merchant_of(B)]

    async with session_factory() as session:
        rows = (await session.execute(select(OutboxEventModel))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.type == "OrderCreated" and row.topic == "orders.events"
    assert row.key == str(order_id) and row.published_at is None
    assert row.payload["total_cents"] == 4480
    assert row.payload["customer_email"] == "maria@example.com"
    assert row.payload["items"][0] == {
        "product_id": str(A),
        "merchant_id": str(merchant_of(A)),
        "quantity": 2,
        "unit_price_cents": 1990,
    }


async def test_failure_before_commit_saves_neither_order_nor_event(uow_factory, session_factory):
    order = Order.create(
        uuid4(), [OrderItem(uuid4(), uuid4(), 1, Money(1000))], "Maria", "maria@example.com"
    )

    with pytest.raises(RuntimeError):
        async with uow_factory() as uow:
            await uow.orders.add(order)
            await uow.outbox.add(order.pull_events())
            raise RuntimeError("boom before commit")

    async with session_factory() as session:
        orders = await session.scalar(select(func.count()).select_from(OrderModel))
        events = await session.scalar(select(func.count()).select_from(OutboxEventModel))
    assert orders == 0 and events == 0


async def test_cancel_reason_is_persisted(uow_factory):
    order = Order.create(
        uuid4(), [OrderItem(uuid4(), uuid4(), 1, Money(1000))], "Maria", "maria@example.com"
    )
    async with uow_factory() as uow:
        await uow.orders.add(order)
        await uow.commit()

    async with uow_factory() as uow:
        stored = await uow.orders.get(order.id, lock=True)
        stored.cancel("out of stock")
        await uow.orders.save(stored)
        await uow.commit()

    async with uow_factory() as uow:
        again = await uow.orders.get(order.id)
    assert again.status is OrderStatus.CANCELLED and again.cancel_reason == "out of stock"


async def test_get_returns_none_for_unknown_order(uow_factory):
    async with uow_factory() as uow:
        assert await uow.orders.get(uuid4()) is None
