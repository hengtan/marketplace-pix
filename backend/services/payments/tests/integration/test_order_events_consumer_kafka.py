import asyncio
import json
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from marketplace_common.messaging import KafkaEventConsumer

from payments.application.handle_order_event import HandleOrderEvent
from payments.config import load_settings
from payments.infrastructure.db.models import InboxMessageModel, PaymentModel
from tests.integration.helpers import count

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


async def send(topic: str, order_id, event_id, total=4480, event_type="OrderCreated") -> None:
    producer = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP)
    await producer.start()
    try:
        await producer.send_and_wait(
            topic,
            key=str(order_id).encode(),
            value=json.dumps(
                {"order_id": str(order_id), "total_cents": total, "currency": "BRL"}
            ).encode(),
            headers=[("event_id", str(event_id).encode()), ("event_type", event_type.encode())],
        )
    finally:
        await producer.stop()


async def run_consumer_until(consumer, predicate, timeout=25.0) -> None:
    stop = asyncio.Event()
    await consumer.start()
    task = asyncio.create_task(consumer.run(stop))
    try:
        async with asyncio.timeout(timeout):
            while not await predicate():
                await asyncio.sleep(0.3)
        await asyncio.sleep(1.5)
    finally:
        stop.set()
        await task
        await consumer.stop()


async def test_consumer_creates_one_payment_even_when_the_event_is_delivered_twice(
    uow_factory, session_factory, psp, topic
):
    order_id, event_id = uuid4(), uuid4()
    await send(topic, order_id, event_id)
    await send(topic, order_id, event_id)
    consumer = KafkaEventConsumer(
        BOOTSTRAP, topic, f"test-{uuid4().hex[:8]}", HandleOrderEvent(uow_factory, psp)
    )

    async def processed() -> bool:
        return await count(session_factory, PaymentModel) >= 1

    await run_consumer_until(consumer, processed)

    assert await count(session_factory, PaymentModel) == 1
    assert await count(session_factory, InboxMessageModel) == 1


async def test_consumer_skips_other_event_types_and_malformed_messages(
    uow_factory, session_factory, psp, topic
):
    producer = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP)
    await producer.start()
    await producer.send_and_wait(topic, key=b"x", value=b"not json", headers=[])
    await producer.stop()
    await send(topic, uuid4(), uuid4(), event_type="OrderPaid")
    order_id = uuid4()
    await send(topic, order_id, uuid4())
    consumer = KafkaEventConsumer(
        BOOTSTRAP, topic, f"test-{uuid4().hex[:8]}", HandleOrderEvent(uow_factory, psp)
    )

    async def processed() -> bool:
        return await count(session_factory, PaymentModel) >= 1

    await run_consumer_until(consumer, processed)

    assert await count(session_factory, PaymentModel) == 1
