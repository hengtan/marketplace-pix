import asyncio
import json
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from marketplace_common.messaging import KafkaEventConsumer

from ordering.application.handle_saga_event import HandleSagaEvent
from ordering.config import load_settings
from ordering.infrastructure.db.models import InboxMessageModel
from tests.integration.helpers import count, make_order, order_status, outbox_types

BOOTSTRAP = load_settings().kafka_bootstrap_servers


@pytest.fixture
async def topic():
    name = f"test.payments.events.{uuid4().hex[:8]}"
    admin = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP)
    await admin.start()
    await admin.create_topics([NewTopic(name, num_partitions=3, replication_factor=1)])
    yield name
    await admin.delete_topics([name])
    await admin.close()


async def send(topic: str, order_id, event_id, event_type: str) -> None:
    producer = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP)
    await producer.start()
    try:
        await producer.send_and_wait(
            topic,
            key=str(order_id).encode(),
            value=json.dumps({"order_id": str(order_id), "payment_id": str(uuid4())}).encode(),
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


async def test_duplicated_payment_confirmed_event_marks_order_paid_once(
    uow_factory, session_factory, topic
):
    order_id, event_id = await make_order(uow_factory), uuid4()
    await send(topic, order_id, event_id, "PaymentConfirmed")
    await send(topic, order_id, event_id, "PaymentConfirmed")
    consumer = KafkaEventConsumer(
        BOOTSTRAP, topic, f"test-{uuid4().hex[:8]}", HandleSagaEvent(uow_factory)
    )

    async def paid() -> bool:
        return await order_status(session_factory, order_id) == "PAID"

    await run_consumer_until(consumer, paid)

    assert await order_status(session_factory, order_id) == "PAID"
    assert await outbox_types(session_factory) == ["OrderCreated", "OrderPaid"]
    assert await count(session_factory, InboxMessageModel) == 1


async def test_payment_expired_event_cancels_the_order(uow_factory, session_factory, topic):
    order_id = await make_order(uow_factory)
    await send(topic, order_id, uuid4(), "PaymentExpired")
    consumer = KafkaEventConsumer(
        BOOTSTRAP, topic, f"test-{uuid4().hex[:8]}", HandleSagaEvent(uow_factory)
    )

    async def cancelled() -> bool:
        return await order_status(session_factory, order_id) == "CANCELLED"

    await run_consumer_until(consumer, cancelled)

    assert await outbox_types(session_factory) == ["OrderCancelled", "OrderCreated"]
