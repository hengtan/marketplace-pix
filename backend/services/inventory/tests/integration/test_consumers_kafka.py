import asyncio
import json
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from marketplace_common.messaging import KafkaEventConsumer
from sqlalchemy import select

from inventory.application.event_handlers import (
    ORDERS_CONSUMER,
    PAYMENTS_CONSUMER,
    HandleOrderEvent,
    HandlePaymentEvent,
)
from inventory.config import load_settings
from inventory.domain.reservation import ReservationStatus
from inventory.infrastructure.db.models import InboxMessageModel, ReservationModel
from tests.integration.helpers import (
    count,
    outbox_types,
    reservation_status,
    set_stock,
    stock_levels,
)

BOOTSTRAP = load_settings().kafka_bootstrap_servers


@pytest.fixture
async def topics():
    suffix = uuid4().hex[:8]
    names = (f"test.orders.events.{suffix}", f"test.payments.events.{suffix}")
    admin = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP)
    await admin.start()
    await admin.create_topics([NewTopic(n, num_partitions=3, replication_factor=1) for n in names])
    yield names
    await admin.delete_topics(list(names))
    await admin.close()


async def send(topic: str, order_id, event_id, event_type: str, **payload) -> None:
    producer = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP)
    await producer.start()
    try:
        await producer.send_and_wait(
            topic,
            key=str(order_id).encode(),
            value=json.dumps({"order_id": str(order_id), **payload}).encode(),
            headers=[("event_id", str(event_id).encode()), ("event_type", event_type.encode())],
        )
    finally:
        await producer.stop()


def order_created_payload(product_id, quantity=2) -> dict:
    return {
        "items": [
            {
                "product_id": str(product_id),
                "merchant_id": str(uuid4()),
                "quantity": quantity,
                "unit_price_cents": 1000,
            }
        ]
    }


async def run_until(consumers, predicate, timeout=25.0, settle=1.5) -> None:
    stop = asyncio.Event()
    for consumer in consumers:
        await consumer.start()
    tasks = [asyncio.create_task(c.run(stop)) for c in consumers]
    try:
        async with asyncio.timeout(timeout):
            while not await predicate():
                await asyncio.sleep(0.3)
        await asyncio.sleep(settle)
    finally:
        stop.set()
        await asyncio.gather(*tasks)
        for consumer in consumers:
            await consumer.stop()


def orders_consumer(uow_factory, topic) -> KafkaEventConsumer:
    return KafkaEventConsumer(
        BOOTSTRAP, topic, f"test-{uuid4().hex[:8]}", HandleOrderEvent(uow_factory)
    )


def payments_consumer(uow_factory, topic, backoff=0.5) -> KafkaEventConsumer:
    return KafkaEventConsumer(
        BOOTSTRAP,
        topic,
        f"test-{uuid4().hex[:8]}",
        HandlePaymentEvent(uow_factory),
        error_backoff=backoff,
    )


async def test_duplicated_order_created_on_kafka_reserves_once(
    uow_factory, session_factory, topics
):
    orders_topic, _ = topics
    product, order_id, event_id = uuid4(), uuid4(), uuid4()
    await set_stock(session_factory, product, 10)
    await send(orders_topic, order_id, event_id, "OrderCreated", **order_created_payload(product))
    await send(orders_topic, order_id, event_id, "OrderCreated", **order_created_payload(product))

    async def reserved() -> bool:
        return await reservation_status(session_factory, order_id) is not None

    await run_until([orders_consumer(uow_factory, orders_topic)], reserved)

    assert await stock_levels(session_factory, product) == (8, 2)
    assert await count(session_factory, ReservationModel) == 1
    assert await count(session_factory, InboxMessageModel) == 1
    assert await outbox_types(session_factory) == ["StockReserved"]


async def test_same_order_with_a_new_event_id_is_still_reserved_once(
    uow_factory, session_factory, topics
):
    orders_topic, _ = topics
    product, order_id = uuid4(), uuid4()
    await set_stock(session_factory, product, 10)
    for _ in range(2):
        await send(
            orders_topic, order_id, uuid4(), "OrderCreated", **order_created_payload(product)
        )

    async def both_seen() -> bool:
        return await count(session_factory, InboxMessageModel) >= 2

    await run_until([orders_consumer(uow_factory, orders_topic)], both_seen)

    assert await stock_levels(session_factory, product) == (8, 2)
    assert await count(session_factory, ReservationModel) == 1


async def test_payment_confirmed_arriving_first_is_retried_until_the_reservation_exists(
    uow_factory, session_factory, topics
):
    orders_topic, payments_topic = topics
    product, order_id = uuid4(), uuid4()
    await set_stock(session_factory, product, 10)
    await send(payments_topic, order_id, uuid4(), "PaymentConfirmed", amount_cents=2000)
    consumers = [
        orders_consumer(uow_factory, orders_topic),
        payments_consumer(uow_factory, payments_topic),
    ]

    async def committed() -> bool:
        if await reservation_status(session_factory, order_id) is None:
            await send(
                orders_topic, order_id, uuid4(), "OrderCreated", **order_created_payload(product)
            )
        return await reservation_status(session_factory, order_id) is ReservationStatus.COMMITTED

    await run_until(consumers, committed, settle=0.5)

    assert await stock_levels(session_factory, product) == (8, 0)
    assert await outbox_types(session_factory) == ["StockReserved", "StockCommitted"]
    async with session_factory() as session:
        consumers_seen = {row.consumer for row in (await session.execute(_inbox())).scalars()}
    assert consumers_seen == {ORDERS_CONSUMER, PAYMENTS_CONSUMER}


async def test_consumer_skips_malformed_messages_and_unrelated_types(
    uow_factory, session_factory, topics
):
    orders_topic, _ = topics
    product, order_id = uuid4(), uuid4()
    await set_stock(session_factory, product, 10)
    producer = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP)
    await producer.start()
    await producer.send_and_wait(orders_topic, key=b"x", value=b"not json", headers=[])
    await producer.stop()
    await send(orders_topic, uuid4(), uuid4(), "OrderPaid")
    await send(orders_topic, order_id, uuid4(), "OrderCreated", **order_created_payload(product))

    async def reserved() -> bool:
        return await reservation_status(session_factory, order_id) is not None

    await run_until([orders_consumer(uow_factory, orders_topic)], reserved)

    assert await stock_levels(session_factory, product) == (8, 2)


async def test_expired_payment_releases_the_stock_via_kafka(uow_factory, session_factory, topics):
    orders_topic, payments_topic = topics
    product, order_id = uuid4(), uuid4()
    await set_stock(session_factory, product, 10)
    await send(orders_topic, order_id, uuid4(), "OrderCreated", **order_created_payload(product))
    consumers = [
        orders_consumer(uow_factory, orders_topic),
        payments_consumer(uow_factory, payments_topic),
    ]
    expiry_sent = False

    async def released() -> bool:
        nonlocal expiry_sent
        if not expiry_sent and await reservation_status(session_factory, order_id) is not None:
            await send(payments_topic, order_id, uuid4(), "PaymentExpired")
            expiry_sent = True
        return await reservation_status(session_factory, order_id) is ReservationStatus.RELEASED

    await run_until(consumers, released, settle=0.5)

    assert await stock_levels(session_factory, product) == (10, 0)


def _inbox():
    return select(InboxMessageModel)
