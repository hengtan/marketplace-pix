import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaConsumer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from marketplace_common.messaging import KafkaPublisher, OutboxRelay
from sqlalchemy import select

from ordering.config import load_settings
from ordering.infrastructure.db.models import OutboxEventModel

BOOTSTRAP = load_settings().kafka_bootstrap_servers


@pytest.fixture
async def topic():
    name = f"test.orders.events.{uuid4().hex[:8]}"
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


async def add_event(session_factory, topic: str) -> OutboxEventModel:
    order_id = uuid4()
    event = OutboxEventModel(
        id=uuid4(),
        aggregate_id=order_id,
        topic=topic,
        key=str(order_id),
        type="OrderCreated",
        payload={"order_id": str(order_id), "total_cents": 4480},
        occurred_at=datetime.now(UTC),
    )
    async with session_factory() as session:
        session.add(event)
        await session.commit()
    return event


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


async def test_relay_delivers_event_to_kafka_and_marks_it_published(
    uow_factory, session_factory, publisher, topic
):
    event = await add_event(session_factory, topic)

    sent = await OutboxRelay(uow_factory, publisher).run_once()

    assert sent == 1
    (record,) = await consume(topic, expected=1)
    assert record.key == event.key.encode()
    assert json.loads(record.value) == event.payload
    headers = dict(record.headers)
    assert headers["event_id"] == str(event.id).encode()
    assert headers["event_type"] == b"OrderCreated"

    async with session_factory() as session:
        row = (await session.execute(select(OutboxEventModel))).scalars().one()
    assert row.published_at is not None


async def test_published_event_is_not_sent_again(uow_factory, session_factory, publisher, topic):
    await add_event(session_factory, topic)
    relay = OutboxRelay(uow_factory, publisher)

    assert await relay.run_once() == 1
    assert await relay.run_once() == 0

    assert len(await consume(topic, expected=2, timeout=3.0)) == 1
