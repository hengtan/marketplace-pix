import asyncio
import json
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from marketplace_common.messaging import KafkaEventConsumer

from notifications.application.handle_event import HandleEvent
from notifications.config import load_settings
from notifications.infrastructure.db.models import InboxMessageModel, NotificationModel
from tests.fakes import FakeQueue
from tests.helpers import NOW, order_cancelled, order_created, payment_created
from tests.integration.helpers import all_notifications, count

BOOTSTRAP = load_settings().kafka_bootstrap_servers


@pytest.fixture
async def topics():
    suffix = uuid4().hex[:8]
    names = (f"test.orders.events.{suffix}", f"test.payments.events.{suffix}")
    admin = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP)
    await admin.start()
    everything = [*names, *(f"{n}.dlq" for n in names)]
    await admin.create_topics(
        [NewTopic(n, num_partitions=3, replication_factor=1) for n in everything]
    )
    yield names
    await admin.delete_topics(everything)
    await admin.close()


async def read_topic(topic: str) -> list:
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=BOOTSTRAP,
        group_id=f"reader-{uuid4().hex[:6]}",
        auto_offset_reset="earliest",
    )
    await consumer.start()
    messages = []
    try:
        async with asyncio.timeout(4):
            while True:
                messages.append(await consumer.getone())
    except TimeoutError:
        pass
    finally:
        await consumer.stop()
    return messages


async def publish(topic: str, event_type: str, event_id: UUID, key: str, payload: dict) -> None:
    producer = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP)
    await producer.start()
    try:
        await producer.send_and_wait(
            topic,
            key=key.encode(),
            value=json.dumps(payload).encode(),
            headers=[("event_id", str(event_id).encode()), ("event_type", event_type.encode())],
        )
    finally:
        await producer.stop()


async def run_consumer_until(
    consumer: KafkaEventConsumer, predicate: Callable[[], Awaitable[bool]], timeout: float = 30.0
) -> None:
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


def make_consumer(topics, uow_factory, queue: FakeQueue, **kwargs) -> KafkaEventConsumer:
    handler = HandleEvent(uow_factory, queue, clock=lambda: NOW)
    return KafkaEventConsumer(
        BOOTSTRAP, topics, f"test-{uuid4().hex[:8]}", handler, error_backoff=0.3, **kwargs
    )


async def test_consumer_turns_a_duplicated_event_into_a_single_notification(
    topics, uow_factory, session_factory
) -> None:
    created = order_created()
    event_id = created.id
    for _ in range(2):
        await publish(topics[0], "OrderCreated", event_id, created.key, created.payload)
    queue = FakeQueue()
    consumer = make_consumer(topics, uow_factory, queue)

    async def processed() -> bool:
        return await count(session_factory, NotificationModel) >= 1

    await run_consumer_until(consumer, processed)

    assert await count(session_factory, NotificationModel) == 1
    assert await count(session_factory, InboxMessageModel) == 1
    assert len(queue.enqueued) == 1


async def test_consumer_reads_both_topics_and_builds_the_whole_conversation(
    topics, uow_factory, session_factory
) -> None:
    created = order_created()
    order_id = UUID(created.payload["order_id"])
    payment = payment_created(order_id)
    cancelled = order_cancelled(order_id, "out of stock")
    await publish(topics[0], "OrderCreated", created.id, created.key, created.payload)
    await publish(topics[1], "PaymentCreated", payment.id, payment.key, payment.payload)
    await publish(topics[0], "OrderCancelled", cancelled.id, cancelled.key, cancelled.payload)
    await publish(topics[0], "StockReserved", uuid4(), created.key, {"order_id": str(order_id)})
    consumer = make_consumer(topics, uow_factory, FakeQueue())

    async def processed() -> bool:
        return await count(session_factory, NotificationModel) >= 3

    await run_consumer_until(consumer, processed)

    kinds = sorted(n.kind for n in await all_notifications(session_factory))
    assert kinds == ["ORDER_CANCELLED", "ORDER_CREATED", "PIX_READY"]


async def test_consumer_retries_an_event_that_arrives_before_the_order_it_depends_on(
    topics, uow_factory, session_factory
) -> None:
    created = order_created()
    order_id = UUID(created.payload["order_id"])
    payment = payment_created(order_id)
    await publish(topics[1], "PaymentCreated", payment.id, payment.key, payment.payload)
    consumer = make_consumer(topics, uow_factory, FakeQueue())
    stop = asyncio.Event()
    await consumer.start()
    task = asyncio.create_task(consumer.run(stop))
    try:
        await asyncio.sleep(2)
        assert await count(session_factory, NotificationModel) == 0
        await publish(topics[0], "OrderCreated", created.id, created.key, created.payload)
        async with asyncio.timeout(30):
            while await count(session_factory, NotificationModel) < 2:
                await asyncio.sleep(0.3)
    finally:
        stop.set()
        await task
        await consumer.stop()

    kinds = sorted(n.kind for n in await all_notifications(session_factory))
    assert kinds == ["ORDER_CREATED", "PIX_READY"]


async def test_consumer_skips_malformed_messages_and_a_poison_event_without_blocking(
    topics, uow_factory, session_factory
) -> None:
    producer = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP)
    await producer.start()
    await producer.send_and_wait(topics[0], key=b"x", value=b"not json", headers=[])
    await producer.stop()
    orphan = payment_created(uuid4())
    await publish(topics[1], "PaymentCreated", orphan.id, orphan.key, orphan.payload)
    created = order_created()
    await publish(topics[0], "OrderCreated", created.id, created.key, created.payload)
    consumer = make_consumer(topics, uow_factory, FakeQueue(), max_attempts=3)

    async def processed() -> bool:
        return await count(session_factory, NotificationModel) >= 1

    await run_consumer_until(consumer, processed)

    (stored,) = await all_notifications(session_factory)
    assert stored.kind == "ORDER_CREATED"
    dead = await read_topic(f"{topics[1]}.dlq")
    assert len(dead) == 1
    headers = {k: v.decode() for k, v in dead[0].headers}
    assert headers["event_type"] == "PaymentCreated"
    assert headers["dlq_source"].startswith(f"{topics[1]}/")
    assert headers["dlq_reason"]
