import asyncio
import json
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaConsumer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from marketplace_common.messaging import KafkaPublisher, OutboxRelay
from sqlalchemy import select, update

from inventory.application.reserve_stock import ReserveStock
from inventory.config import load_settings
from inventory.infrastructure.db.models import OutboxEventModel
from tests.integration.helpers import items, set_stock

BOOTSTRAP = load_settings().kafka_bootstrap_servers


@pytest.fixture
async def topic():
    name = f"test.inventory.events.{uuid4().hex[:8]}"
    admin = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP)
    await admin.start()
    await admin.create_topics([NewTopic(name, num_partitions=3, replication_factor=1)])
    yield name
    await admin.delete_topics([name])
    await admin.close()


@pytest.fixture
async def publisher():
    publisher = KafkaPublisher(BOOTSTRAP)
    await publisher.start()
    yield publisher
    await publisher.stop()


async def redirect_outbox(session_factory, topic: str) -> None:
    async with session_factory() as session:
        await session.execute(update(OutboxEventModel).values(topic=topic))
        await session.commit()


async def consume(topic: str, expected: int, timeout: float = 10.0) -> list:
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=BOOTSTRAP,
        group_id=f"test-{uuid4().hex[:8]}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await consumer.start()
    received = []
    try:
        async with asyncio.timeout(timeout):
            while len(received) < expected:
                received.append(await consumer.getone())
    except TimeoutError:
        pass
    finally:
        await consumer.stop()
    return received


async def test_relay_publishes_stock_events_following_the_contract(
    uow_factory, session_factory, publisher, topic
):
    product, scarce, reserved_order, rejected_order = uuid4(), uuid4(), uuid4(), uuid4()
    await set_stock(session_factory, product, 10)
    await set_stock(session_factory, scarce, 1)
    reserve = ReserveStock(uow_factory)
    await reserve.execute(reserved_order, items((product, 2)))
    await reserve.execute(rejected_order, items((scarce, 3)))
    await redirect_outbox(session_factory, topic)

    sent = await OutboxRelay(uow_factory, publisher).run_once()

    assert sent == 2
    records = {r.key.decode(): r for r in await consume(topic, expected=2)}
    reserved = records[str(reserved_order)]
    assert dict(reserved.headers)["event_type"] == b"StockReserved"
    assert json.loads(reserved.value)["order_id"] == str(reserved_order)
    rejected = records[str(rejected_order)]
    assert dict(rejected.headers)["event_type"] == b"StockRejected"
    body = json.loads(rejected.value)
    assert body["reason"] == "insufficient_stock"
    assert body["missing"] == [{"product_id": str(scarce), "requested": 3, "available": 1}]
    assert "event_id" in body and "occurred_at" in body


async def test_published_events_are_not_sent_again(uow_factory, session_factory, publisher, topic):
    product = uuid4()
    await set_stock(session_factory, product, 10)
    await ReserveStock(uow_factory).execute(uuid4(), items((product, 1)))
    await redirect_outbox(session_factory, topic)
    relay = OutboxRelay(uow_factory, publisher)

    assert await relay.run_once() == 1
    assert await relay.run_once() == 0

    assert len(await consume(topic, expected=2, timeout=3.0)) == 1
    async with session_factory() as session:
        row = (await session.execute(select(OutboxEventModel))).scalars().one()
    assert row.published_at is not None
