from uuid import uuid4

import pytest

from ordering.application.create_order import CreateOrder, CreateOrderCommand, CreateOrderItem
from ordering.application.errors import IdempotencyKeyReused
from ordering.domain.events import OrderCreated
from tests.fakes import FakeDatabase, FakeUow


def command(customer_id=None, qty=2) -> CreateOrderCommand:
    return CreateOrderCommand(
        customer_id=customer_id or uuid4(),
        items=[CreateOrderItem(uuid4(), qty, 1990), CreateOrderItem(uuid4(), 1, 500)],
    )


async def test_creates_order_and_writes_event_to_outbox():
    db = FakeDatabase()
    result = await CreateOrder(lambda: FakeUow(db)).execute(command())

    assert not result.replayed
    assert result.order_id in db.orders
    assert len(db.events) == 1
    assert isinstance(db.events[0], OrderCreated)
    assert db.events[0].total_cents == 4480


async def test_same_key_and_same_body_returns_the_same_order_without_duplicating():
    db = FakeDatabase()
    use_case = CreateOrder(lambda: FakeUow(db))
    cmd = command()

    first = await use_case.execute(cmd, "key-1")
    second = await use_case.execute(cmd, "key-1")

    assert second.order_id == first.order_id
    assert second.replayed and not first.replayed
    assert len(db.orders) == 1
    assert len(db.events) == 1


async def test_same_key_with_different_body_is_rejected():
    db = FakeDatabase()
    use_case = CreateOrder(lambda: FakeUow(db))
    customer = uuid4()

    await use_case.execute(command(customer, qty=2), "key-1")
    with pytest.raises(IdempotencyKeyReused):
        await use_case.execute(command(customer, qty=3), "key-1")

    assert len(db.orders) == 1


async def test_different_keys_create_different_orders():
    db = FakeDatabase()
    use_case = CreateOrder(lambda: FakeUow(db))
    cmd = command()

    await use_case.execute(cmd, "key-1")
    await use_case.execute(cmd, "key-2")

    assert len(db.orders) == 2
