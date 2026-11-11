import asyncio
import json
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaProducer

from marketplace_common.dlq.cli import main
from marketplace_common.messaging import IncomingEvent, KafkaEventConsumer
from tests.integration.conftest import BOOTSTRAP
from tests.integration.helpers import read_all, send, wait_until


class SwitchableHandler:
    def __init__(self, broken: bool) -> None:
        self.broken = broken
        self.calls = 0
        self.processed: list[str] = []

    async def handle(self, event: IncomingEvent) -> None:
        self.calls += 1
        if self.broken:
            raise RuntimeError("dependency down")
        self.processed.append(event.payload["name"])


async def put_dlq(dlq: str, source: str, name: str, event_type: str, reason: str) -> None:
    producer = AIOKafkaProducer(bootstrap_servers=BOOTSTRAP)
    await producer.start()
    try:
        await producer.send_and_wait(
            dlq,
            key=name.encode(),
            value=json.dumps({"name": name}).encode(),
            headers=[
                ("event_id", str(uuid4()).encode()),
                ("event_type", event_type.encode()),
                ("dlq_reason", reason.encode()),
                ("dlq_source", f"{source}/0/{uuid4().int % 1000}".encode()),
                ("dlq_group", b"payments"),
            ],
        )
    finally:
        await producer.stop()


async def cli(*args: str) -> int:
    return await asyncio.to_thread(main, ["--bootstrap", BOOTSTRAP, *args])


async def test_list_summarizes_origin_type_reason_and_count(
    topics: tuple[str, str], capsys: pytest.CaptureFixture[str]
):
    source, dlq = topics
    await put_dlq(dlq, source, "a", "OrderCreated", "RuntimeError('db down')")
    await put_dlq(dlq, source, "b", "OrderCreated", "RuntimeError('db down')")
    await put_dlq(dlq, source, "c", "OrderCancelled", "ValueError('bad')")

    assert await cli("list", "--topic", dlq) == 0

    out = capsys.readouterr().out
    assert f"{dlq}: 3 message(s)" in out
    assert source in out
    assert "OrderCreated" in out and "OrderCancelled" in out
    assert "RuntimeError('db down')" in out
    assert await cli("list", "--topic", dlq, "--json") == 0
    rows = json.loads(capsys.readouterr().out)
    assert sorted(r["count"] for r in rows) == [1, 2]


async def test_list_of_an_empty_topic(topics: tuple[str, str], capsys: pytest.CaptureFixture[str]):
    _, dlq = topics

    assert await cli("list", "--topic", dlq) == 0

    assert "empty" in capsys.readouterr().out


async def test_replay_is_a_dry_run_by_default(topics: tuple[str, str], capsys):
    source, dlq = topics
    await put_dlq(dlq, source, "a", "OrderCreated", "boom")

    assert await cli("replay", "--topic", dlq) == 0

    assert "DRY RUN" in capsys.readouterr().out
    assert await read_all(source, timeout=2.0) == []
    assert len(await read_all(dlq, timeout=2.0)) == 1


async def test_replay_republishes_filtered_messages_once(topics: tuple[str, str], capsys):
    source, dlq = topics
    await put_dlq(dlq, source, "a", "OrderCreated", "boom")
    await put_dlq(dlq, source, "b", "OrderCancelled", "boom")
    await put_dlq(dlq, source, "c", "OrderCreated", "boom")

    assert (
        await cli("replay", "--topic", dlq, "--event-type", "OrderCreated", "--limit", "1", "--yes")
        == 0
    )

    (sent,) = await read_all(source, timeout=3.0)
    headers = {k: v.decode() for k, v in sent.headers}
    assert json.loads(sent.value) == {"name": "a"}
    assert sent.key == b"a"
    assert headers["event_type"] == "OrderCreated"
    assert "dlq_replayed" in headers
    assert headers["dlq_replayed_from"].startswith(f"{dlq}/0/")
    assert not any(name.startswith("dlq_reason") for name in headers)

    capsys.readouterr()
    assert await cli("replay", "--topic", dlq, "--event-type", "OrderCreated", "--yes") == 0
    out = capsys.readouterr().out
    assert "skipped_already_replayed=1" in out
    assert [json.loads(r.value)["name"] for r in await read_all(source, timeout=3.0)] == ["a", "c"]


async def test_force_replays_again(topics: tuple[str, str]):
    source, dlq = topics
    await put_dlq(dlq, source, "a", "OrderCreated", "boom")

    await cli("replay", "--topic", dlq, "--yes")
    await cli("replay", "--topic", dlq, "--yes")
    assert len(await read_all(source, timeout=3.0)) == 1

    await cli("replay", "--topic", dlq, "--yes", "--force")
    assert len(await read_all(source, timeout=3.0)) == 2


async def consume(source: str, group: str, handler: SwitchableHandler, done) -> None:
    consumer = KafkaEventConsumer(
        BOOTSTRAP, source, group, handler, error_backoff=0.05, max_attempts=2
    )
    stop = asyncio.Event()
    await consumer.start()
    task = asyncio.create_task(consumer.run(stop))
    try:
        await wait_until(done)
    finally:
        stop.set()
        await task
        await consumer.stop()


async def test_dead_letter_then_replay_after_the_fix_processes_the_event(
    topics: tuple[str, str], capsys: pytest.CaptureFixture[str]
):
    source, dlq = topics
    group = f"g-{uuid4().hex[:6]}"
    await send(source, "order", event_type="OrderCreated")
    handler = SwitchableHandler(broken=True)
    await consume(source, group, handler, lambda: handler.calls >= 2)
    assert len(await read_all(dlq, timeout=2.0)) == 1

    assert await cli("replay", "--topic", dlq, "--yes") == 0
    handler.broken = False
    await consume(source, group, handler, lambda: handler.processed == ["order"])

    capsys.readouterr()
    assert await cli("replay", "--topic", dlq, "--yes") == 0
    assert "sent=0" in capsys.readouterr().out
    assert handler.processed == ["order"]


async def test_message_that_fails_again_after_replay_is_not_replayed_in_a_loop(
    topics: tuple[str, str], capsys: pytest.CaptureFixture[str]
):
    source, dlq = topics
    group = f"g-{uuid4().hex[:6]}"
    await send(source, "stubborn")
    handler = SwitchableHandler(broken=True)
    await consume(source, group, handler, lambda: handler.calls >= 2)

    await cli("replay", "--topic", dlq, "--yes")
    await consume(source, group, handler, lambda: handler.calls >= 4)
    dead = [r for r in await read_all(dlq, timeout=2.0) if r.value]
    assert len(dead) == 2
    assert any(name == "dlq_replayed" for r in dead for name, _ in r.headers)

    capsys.readouterr()
    await cli("replay", "--topic", dlq, "--yes")
    out = capsys.readouterr().out
    assert "sent=0" in out
    assert "skipped_already_replayed=2" in out
    assert len(await read_all(source, timeout=2.0)) == 2
