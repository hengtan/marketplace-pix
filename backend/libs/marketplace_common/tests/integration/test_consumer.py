import asyncio
import json
from uuid import uuid4

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from prometheus_client import REGISTRY

from marketplace_common.messaging import IncomingEvent, KafkaEventConsumer
from tests.integration.conftest import BOOTSTRAP
from tests.integration.helpers import read_all, send, wait_until


class PickyHandler:
    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        self.ok: list[str] = []
        self.types: list[str] = []

    async def handle(self, event: IncomingEvent) -> None:
        name = event.payload["name"]
        self.calls[name] = self.calls.get(name, 0) + 1
        if name == "poison":
            raise RuntimeError("cannot process this one")
        self.ok.append(name)
        self.types.append(event.type)


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def run_until(consumer: KafkaEventConsumer, done) -> None:
    stop = asyncio.Event()
    await consumer.start()
    task = asyncio.create_task(consumer.run(stop))
    try:
        await wait_until(done)
    finally:
        stop.set()
        await task
        await consumer.stop()


async def test_poison_message_goes_to_dlq_and_the_next_message_is_still_processed(topics):
    topic, dlq = topics
    group = f"g-{uuid4().hex[:6]}"
    await send(topic, "poison", event_type="Poisoned")
    await send(topic, "good")
    handler = PickyHandler()
    consumer = KafkaEventConsumer(
        BOOTSTRAP, topic, group, handler, error_backoff=0.05, max_attempts=3
    )

    await run_until(consumer, lambda: "good" in handler.ok)

    assert handler.calls["poison"] == 3
    (dead,) = await read_all(dlq)
    headers = {k: v.decode() for k, v in dead.headers}
    assert json.loads(dead.value) == {"name": "poison"}
    assert "cannot process this one" in headers["dlq_reason"]
    assert headers["dlq_source"].startswith(f"{topic}/0/")
    assert headers["dlq_group"] == group
    assert headers["event_type"] == "Poisoned"
    assert sample("marketplace_dlq_messages_total", source_topic=topic, consumer_group=group) == 1
    assert (
        sample(
            "marketplace_handler_duration_seconds_count",
            consumer_group=group,
            event_type="Poisoned",
            result="error",
        )
        == 3
    )
    assert (
        sample(
            "marketplace_handler_duration_seconds_count",
            consumer_group=group,
            event_type="Anything",
            result="success",
        )
        == 1
    )


async def test_malformed_message_is_skipped(topics):
    topic, _ = topics
    from aiokafka import AIOKafkaProducer

    producer = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP)
    await producer.start()
    await producer.send_and_wait(topic, key=b"k", value=b"not json", headers=[])
    await producer.stop()
    await send(topic, "good")
    handler = PickyHandler()
    consumer = KafkaEventConsumer(BOOTSTRAP, topic, f"g-{uuid4().hex[:6]}", handler)

    await run_until(consumer, lambda: handler.ok == ["good"])

    assert handler.calls == {"good": 1}


async def test_multiple_topics_each_dead_letter_to_their_own_dlq():
    base = f"test.common.multi.{uuid4().hex[:8]}"
    names = [f"{base}.a", f"{base}.b", f"{base}.a.dlq", f"{base}.b.dlq"]
    admin = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP)
    await admin.start()
    await admin.create_topics([NewTopic(n, num_partitions=1, replication_factor=1) for n in names])
    try:
        await send(names[0], "poison")
        await send(names[1], "poison")
        await send(names[1], "good")
        handler = PickyHandler()
        consumer = KafkaEventConsumer(
            BOOTSTRAP,
            [names[0], names[1]],
            f"g-{uuid4().hex[:6]}",
            handler,
            error_backoff=0.05,
            max_attempts=2,
        )

        await run_until(
            consumer, lambda: handler.calls.get("poison", 0) >= 4 and "good" in handler.ok
        )

        (dead_a,) = await read_all(names[2])
        (dead_b,) = await read_all(names[3])
        assert dict(dead_a.headers)["dlq_source"].decode().startswith(f"{names[0]}/0/")
        assert dict(dead_b.headers)["dlq_source"].decode().startswith(f"{names[1]}/0/")
        assert "good" in handler.ok
    finally:
        await admin.delete_topics(names)
        await admin.close()
