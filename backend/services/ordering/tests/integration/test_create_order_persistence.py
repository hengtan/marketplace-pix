from uuid import uuid4

import pytest
from sqlalchemy import func, select

from ordering.application.create_order import CreateOrder, CreateOrderCommand, CreateOrderItem
from ordering.domain.money import Money
from ordering.domain.order import Order, OrderItem, OrderStatus
from ordering.infrastructure.db.models import OrderModel, OutboxEventModel


def command() -> CreateOrderCommand:
    return CreateOrderCommand(
        customer_id=uuid4(),
        items=[CreateOrderItem(uuid4(), 2, 1990), CreateOrderItem(uuid4(), 1, 500)],
    )


async def test_order_and_outbox_event_are_saved_together(uow_factory, session_factory):
    order_id = (await CreateOrder(uow_factory).execute(command())).order_id

    async with uow_factory() as uow:
        order = await uow.orders.get(order_id)
    assert order is not None
    assert order.status is OrderStatus.PENDING
    assert order.total == Money(4480)
    assert len(order.items) == 2

    async with session_factory() as session:
        rows = (await session.execute(select(OutboxEventModel))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.type == "OrderCreated"
    assert row.topic == "orders.events"
    assert row.key == str(order_id)
    assert row.published_at is None
    assert row.payload["total_cents"] == 4480
    assert row.payload["order_id"] == str(order_id)


async def test_failure_before_commit_saves_neither_order_nor_event(uow_factory, session_factory):
    order = Order.create(uuid4(), [OrderItem(uuid4(), 1, Money(1000))])

    with pytest.raises(RuntimeError):
        async with uow_factory() as uow:
            await uow.orders.add(order)
            await uow.outbox.add(order.pull_events())
            raise RuntimeError("boom before commit")

    async with session_factory() as session:
        orders = await session.scalar(select(func.count()).select_from(OrderModel))
        events = await session.scalar(select(func.count()).select_from(OutboxEventModel))
    assert orders == 0
    assert events == 0


async def test_get_returns_none_for_unknown_order(uow_factory):
    async with uow_factory() as uow:
        assert await uow.orders.get(uuid4()) is None
