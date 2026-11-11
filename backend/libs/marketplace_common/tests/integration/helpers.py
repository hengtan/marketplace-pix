import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from tests.integration.conftest import BOOTSTRAP


async def send(
    topic: str,
    name: str,
    event_type: str = "Anything",
    extra_headers: list[tuple[str, bytes]] | None = None,
) -> str:
    event_id = str(uuid4())
    producer = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP)
    await producer.start()
    try:
        await producer.send_and_wait(
            topic,
            key=name.encode(),
            value=json.dumps({"name": name}).encode(),
            headers=[
                ("event_id", event_id.encode()),
                ("event_type", event_type.encode()),
                *(extra_headers or []),
            ],
        )
    finally:
        await producer.stop()
    return event_id


async def read_all(topic: str, timeout: float = 4.0) -> list[Any]:
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=BOOTSTRAP,
        group_id=f"reader-{uuid4().hex[:6]}",
        auto_offset_reset="earliest",
    )
    await consumer.start()
    messages: list[Any] = []
    try:
        async with asyncio.timeout(timeout):
            while True:
                messages.append(await consumer.getone())
    except TimeoutError:
        pass
    finally:
        await consumer.stop()
    return messages


async def wait_until(
    predicate: Callable[[], bool | Awaitable[bool]], timeout: float = 25.0
) -> None:
    async with asyncio.timeout(timeout):
        while True:
            result = predicate()
            if (await result) if isinstance(result, Awaitable) else result:
                return
            await asyncio.sleep(0.1)
