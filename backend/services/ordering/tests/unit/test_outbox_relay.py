from uuid import UUID, uuid4

import pytest

from ordering.application.outbox_relay import OutboxRelay
from ordering.application.ports import OutboxMessage


def message(n: int) -> OutboxMessage:
    return OutboxMessage(
        id=uuid4(), topic="orders.events", key=f"order-{n}", type="OrderCreated", payload={"n": n}
    )


class FakeStore:
    def __init__(self, messages: list[OutboxMessage]) -> None:
        self.pending = list(messages)
        self.published_ids: set[UUID] = set()
        self._marks: list[UUID] = []

    async def fetch_pending(self, limit: int) -> list[OutboxMessage]:
        return [m for m in self.pending if m.id not in self.published_ids][:limit]

    async def mark_published(self, ids: list[UUID]) -> None:
        self._marks.extend(ids)

    def apply_marks(self) -> None:
        self.published_ids.update(self._marks)
        self._marks = []

    def discard_marks(self) -> None:
        self._marks = []


class FakeUow:
    def __init__(self, store: FakeStore, fail_commit: bool = False) -> None:
        self.outbox_store = store
        self._fail_commit = fail_commit

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> None:
        self.outbox_store.discard_marks()

    async def commit(self) -> None:
        if self._fail_commit:
            raise RuntimeError("db died after publishing")
        self.outbox_store.apply_marks()


class FakePublisher:
    def __init__(self, fail_on: int | None = None) -> None:
        self.sent: list[OutboxMessage] = []
        self._fail_on = fail_on

    async def publish(self, msg: OutboxMessage) -> None:
        if self._fail_on is not None and len(self.sent) == self._fail_on:
            raise ConnectionError("kafka down")
        self.sent.append(msg)


async def test_publishes_pending_in_order_and_marks_them():
    store = FakeStore([message(1), message(2), message(3)])
    publisher = FakePublisher()

    count = await OutboxRelay(lambda: FakeUow(store), publisher).run_once()

    assert count == 3
    assert [m.key for m in publisher.sent] == ["order-1", "order-2", "order-3"]
    assert len(store.published_ids) == 3


async def test_nothing_pending_publishes_nothing():
    store = FakeStore([])
    publisher = FakePublisher()

    assert await OutboxRelay(lambda: FakeUow(store), publisher).run_once() == 0
    assert publisher.sent == []


async def test_respects_batch_size():
    store = FakeStore([message(i) for i in range(5)])
    publisher = FakePublisher()
    relay = OutboxRelay(lambda: FakeUow(store), publisher, batch_size=2)

    assert await relay.run_once() == 2
    assert await relay.run_once() == 2
    assert await relay.run_once() == 1
    assert await relay.run_once() == 0


async def test_publish_failure_marks_only_the_published_prefix():
    msgs = [message(1), message(2), message(3)]
    store = FakeStore(msgs)
    publisher = FakePublisher(fail_on=1)

    with pytest.raises(ConnectionError):
        await OutboxRelay(lambda: FakeUow(store), publisher).run_once()

    assert store.published_ids == {msgs[0].id}

    recovered = FakePublisher()
    await OutboxRelay(lambda: FakeUow(store), recovered).run_once()
    assert [m.key for m in recovered.sent] == ["order-2", "order-3"]


async def test_crash_between_publish_and_commit_causes_redelivery():
    msgs = [message(1), message(2)]
    store = FakeStore(msgs)
    first = FakePublisher()

    with pytest.raises(RuntimeError):
        await OutboxRelay(lambda: FakeUow(store, fail_commit=True), first).run_once()

    assert len(first.sent) == 2
    assert store.published_ids == set()

    second = FakePublisher()
    await OutboxRelay(lambda: FakeUow(store), second).run_once()

    assert {m.id for m in second.sent} == {m.id for m in first.sent}
