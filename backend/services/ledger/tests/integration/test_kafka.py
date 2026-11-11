import asyncio
import json
from uuid import UUID, uuid4

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from sqlalchemy import select, update

from ledger.application.outbox_relay import OutboxRelay
from ledger.config import load_settings
from ledger.infrastructure.db.models import (
    InboxMessageModel,
    OrderProjectionModel,
    OutboxEventModel,
    TransactionModel,
)
from ledger.infrastructure.messaging.kafka_consumer import KafkaEventConsumer
from ledger.infrastructure.messaging.kafka_publisher import KafkaPublisher
from tests.builders import order_created, payment_confirmed
from tests.integration.helpers import balances, count

BOOTSTRAP = load_settings().kafka_bootstrap_servers


async def _create_topic(prefix: str) -> str:
    name = f"test.{prefix}.{uuid4().hex[:8]}"
    admin = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP)
    await admin.start()
    await admin.create_topics([NewTopic(name, num_partitions=3, replication_factor=1)])
    await admin.close()
    return name


async def _delete_topic(name: str) -> None:
    admin = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP)
    await admin.start()
    await admin.delete_topics([name])
    await admin.close()


@pytest.fixture
async def orders_topic():
    name = await _create_topic("orders.events")
    yield name
    await _delete_topic(name)


@pytest.fixture
async def payments_topic():
    name = await _create_topic("payments.events")
    yield name
    await _delete_topic(name)


@pytest.fixture
async def ledger_topic():
    name = await _create_topic("ledger.events")
    yield name
    await _delete_topic(name)


async def send(topic: str, key: str, event_id: UUID, event_type: str, payload: dict) -> None:
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


async def send_order(topic: str, event) -> None:
    await send(topic, event.key, event.id, event.type, event.payload)


async def send_payment(topic: str, order_id: UUID, amount: int, event_id: UUID | None = None):
    await send(
        topic,
        str(order_id),
        event_id or uuid4(),
        "PaymentConfirmed",
        {
            "order_id": str(order_id),
            "payment_id": str(uuid4()),
            "amount_cents": amount,
            "currency": "BRL",
        },
    )


async def run_consumers_until(consumers, predicate, timeout=40.0) -> None:
    stop = asyncio.Event()
    for consumer in consumers:
        await consumer.start()
    tasks = [asyncio.create_task(c.run(stop)) for c in consumers]
    try:
        async with asyncio.timeout(timeout):
            while not await predicate():
                await asyncio.sleep(0.3)
        await asyncio.sleep(1.5)
    finally:
        stop.set()
        await asyncio.gather(*tasks)
        for consumer in consumers:
            await consumer.stop()


def make_consumer(topic, handler):
    return KafkaEventConsumer(
        BOOTSTRAP, topic, f"test-{uuid4().hex[:8]}", handler, error_backoff=0.5
    )


async def test_orders_consumer_projects_once_even_when_the_event_is_delivered_twice(
    order_handler, session_factory, orders_topic
):
    event = order_created(lines=[(uuid4(), 2, 1500)])
    await send_order(orders_topic, event)
    await send_order(orders_topic, event)

    async def projected() -> bool:
        return await count(session_factory, OrderProjectionModel) >= 1

    await run_consumers_until([make_consumer(orders_topic, order_handler)], projected)

    assert await count(session_factory, OrderProjectionModel) == 1
    assert await count(session_factory, InboxMessageModel) == 1


async def test_payment_consumer_posts_once_when_the_event_is_delivered_twice(
    order_handler, payment_handler, session_factory, orders_topic, payments_topic
):
    merchant = uuid4()
    order = order_created(lines=[(merchant, 1, 10000)])
    order_id = UUID(order.payload["order_id"])
    await order_handler.handle(order)
    event_id = uuid4()
    await send_payment(payments_topic, order_id, 10000, event_id)
    await send_payment(payments_topic, order_id, 10000, event_id)
    await send_payment(payments_topic, order_id, 10000)

    async def posted() -> bool:
        return await count(session_factory, TransactionModel) >= 1

    await run_consumers_until([make_consumer(payments_topic, payment_handler)], posted)

    assert await count(session_factory, TransactionModel) == 1
    state = await balances(session_factory)
    assert state[f"merchant:{merchant}"] == 9000
    assert state["platform:revenue"] == 1000
    assert state["psp:receivable"] == 10000


async def test_payment_arriving_before_the_order_is_retried_until_the_projection_exists(
    order_handler, payment_handler, session_factory, orders_topic, payments_topic
):
    merchant = uuid4()
    order = order_created(lines=[(merchant, 1, 7777)])
    order_id = UUID(order.payload["order_id"])
    await send_payment(payments_topic, order_id, 7777)
    payments = make_consumer(payments_topic, payment_handler)
    orders = make_consumer(orders_topic, order_handler)
    stop = asyncio.Event()
    await payments.start()
    await orders.start()
    tasks = [asyncio.create_task(payments.run(stop)), asyncio.create_task(orders.run(stop))]
    try:
        await asyncio.sleep(3.0)
        assert await count(session_factory, TransactionModel) == 0

        await send_order(orders_topic, order)

        async with asyncio.timeout(40):
            while await count(session_factory, TransactionModel) < 1:
                await asyncio.sleep(0.3)
        await asyncio.sleep(1.0)
    finally:
        stop.set()
        await asyncio.gather(*tasks)
        await payments.stop()
        await orders.stop()

    assert await count(session_factory, TransactionModel) == 1
    state = await balances(session_factory)
    assert state[f"merchant:{merchant}"] == 7777 - 778


async def test_consumers_skip_unrelated_and_malformed_messages(
    order_handler, session_factory, orders_topic
):
    producer = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP)
    await producer.start()
    await producer.send_and_wait(orders_topic, key=b"x", value=b"not json", headers=[])
    await producer.stop()
    await send(orders_topic, str(uuid4()), uuid4(), "OrderPaid", {"order_id": str(uuid4())})
    await send(orders_topic, "k", uuid4(), "OrderCreated", {"order_id": "broken"})
    await send_order(orders_topic, order_created())

    async def projected() -> bool:
        return await count(session_factory, OrderProjectionModel) >= 1

    await run_consumers_until([make_consumer(orders_topic, order_handler)], projected)

    assert await count(session_factory, OrderProjectionModel) == 1


async def test_relay_publishes_the_posted_transaction_event(
    order_handler, payment_handler, session_factory, uow_factory, ledger_topic
):
    order = order_created(lines=[(uuid4(), 1, 10000), (uuid4(), 1, 5)])
    order_id = UUID(order.payload["order_id"])
    await order_handler.handle(order)
    await payment_handler.handle(payment_confirmed(order_id, 10005))
    async with session_factory() as session:
        await session.execute(update(OutboxEventModel).values(topic=ledger_topic))
        await session.commit()
    publisher = KafkaPublisher(BOOTSTRAP)
    await publisher.start()
    try:
        sent = await OutboxRelay(uow_factory, publisher).run_once()
    finally:
        await publisher.stop()
    assert sent == 1

    consumer = AIOKafkaConsumer(
        ledger_topic,
        bootstrap_servers=BOOTSTRAP,
        group_id=f"test-{uuid4().hex[:8]}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await consumer.start()
    try:
        async with asyncio.timeout(15):
            record = await consumer.getone()
    finally:
        await consumer.stop()

    body = json.loads(record.value)
    headers = dict(record.headers)
    assert record.key == str(order_id).encode()
    assert headers["event_type"] == b"LedgerTransactionPosted"
    assert body["order_id"] == str(order_id)
    assert body["total_cents"] == 10005
    assert body["platform_fee_cents"] == 1001
    assert set(body) >= {"transaction_id", "event_id", "occurred_at"}
    async with session_factory() as session:
        row = (await session.execute(select(OutboxEventModel))).scalars().one()
    assert row.published_at is not None
    assert headers["event_id"] == str(row.id).encode()
