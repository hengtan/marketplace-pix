import asyncio
import json
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic

from inventory.config import load_settings
from inventory.infrastructure.messaging.kafka_consumer import KafkaEventConsumer

BOOTSTRAP = load_settings().kafka_bootstrap_servers


@pytest.fixture
async def topics():
    base = f"test.dlq.{uuid4().hex[:8]}"
    names = [base, f"{base}.dlq"]
    admin = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP)
    await admin.start()
    await admin.create_topics([NewTopic(n, num_partitions=1, replication_factor=1) for n in names])
    yield base, names[1]
    await admin.delete_topics(names)
    await admin.close()


class PickyHandler:
    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        self.ok: list[str] = []

    async def handle(self, event) -> None:
        name = event.payload["name"]
        self.calls[name] = self.calls.get(name, 0) + 1
        if name == "poison":
            raise RuntimeError("cannot process this one")
        self.ok.append(name)


async def send(topic: str, name: str) -> None:
    producer = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP)
    await producer.start()
    try:
        await producer.send_and_wait(
            topic,
            key=b"k",
            value=json.dumps({"name": name}).encode(),
            headers=[("event_id", str(uuid4()).encode()), ("event_type", b"Anything")],
        )
    finally:
        await producer.stop()


async def read_dlq(dlq: str) -> list:
    consumer = AIOKafkaConsumer(
        dlq,
        bootstrap_servers=BOOTSTRAP,
        group_id=f"dlq-reader-{uuid4().hex[:6]}",
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


async def test_poison_message_goes_to_dlq_and_the_next_message_is_still_processed(topics):
    topic, dlq = topics
    await send(topic, "poison")
    await send(topic, "good")
    handler = PickyHandler()
    consumer = KafkaEventConsumer(
        BOOTSTRAP, topic, f"g-{uuid4().hex[:6]}", handler, error_backoff=0.05, max_attempts=3
    )
    stop = asyncio.Event()
    await consumer.start()
    task = asyncio.create_task(consumer.run(stop))
    try:
        async with asyncio.timeout(25):
            while "good" not in handler.ok:
                await asyncio.sleep(0.2)
    finally:
        stop.set()
        await task
        await consumer.stop()

    assert handler.calls["poison"] == 3
    (dead,) = await read_dlq(dlq)
    headers = {k: v.decode() for k, v in dead.headers}
    assert json.loads(dead.value) == {"name": "poison"}
    assert "cannot process this one" in headers["dlq_reason"]
    assert headers["dlq_source"].startswith(f"{topic}/0/")
    assert headers["event_type"] == "Anything"
