import asyncio
from uuid import UUID, uuid4

from marketplace_common.events import golden_payload
from marketplace_common.events.models import OrderCreatedV2
from marketplace_common.messaging import (
    IncomingEvent,
    KafkaEventConsumer,
    KafkaPublisher,
    OutboxMessage,
)
from tests.integration.conftest import BOOTSTRAP
from tests.integration.helpers import read_all, wait_until


class Collector:
    def __init__(self) -> None:
        self.events: list[IncomingEvent] = []

    async def handle(self, event: IncomingEvent) -> None:
        self.events.append(event)


async def publish(topic: str, payload: dict) -> None:
    publisher = KafkaPublisher(BOOTSTRAP)
    await publisher.start()
    try:
        await publisher.publish(
            OutboxMessage(
                id=uuid4(),
                topic=topic,
                key=payload["order_id"],
                type="OrderCreated",
                payload=payload,
            )
        )
    finally:
        await publisher.stop()


async def test_publisher_stamps_the_schema_version_header_from_the_payload(topics):
    topic, _ = topics
    await publish(topic, golden_payload("OrderCreated", 2))
    await publish(
        topic, {k: v for k, v in golden_payload("OrderCreated", 1).items() if k != "schema_version"}
    )

    first, second = await read_all(topic)

    assert dict(first.headers)["schema_version"] == b"2"
    assert dict(second.headers)["schema_version"] == b"1"


async def test_consumer_parses_old_and_new_messages_into_the_latest_model(topics):
    topic, _ = topics
    await publish(topic, golden_payload("OrderCreated", 1))
    await publish(topic, golden_payload("OrderCreated", 2))
    collector = Collector()
    consumer = KafkaEventConsumer(BOOTSTRAP, topic, f"g-{uuid4().hex[:6]}", collector)

    stop = asyncio.Event()
    await consumer.start()
    task = asyncio.create_task(consumer.run(stop))
    try:
        await wait_until(lambda: len(collector.events) == 2)
    finally:
        stop.set()
        await task
        await consumer.stop()

    assert [e.schema_version for e in collector.events] == [1, 2]
    models = [e.parse() for e in collector.events]
    assert all(isinstance(m, OrderCreatedV2) for m in models)
    assert [m.customer_type for m in models] == [None, "registered"]
    assert models[0].order_id == UUID(golden_payload("OrderCreated", 1)["order_id"])
