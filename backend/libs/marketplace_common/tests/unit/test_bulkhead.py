import asyncio

import pytest
from prometheus_client import REGISTRY

from marketplace_common.resilience import Bulkhead, BulkheadFullError
from tests.unit.fakes import FakeClock


def value(metric_name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(metric_name, labels) or 0.0


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_limits_concurrency_and_rejects_when_queue_is_zero() -> None:
    bulkhead = Bulkhead("b-full", max_concurrent=2, max_queue=0)
    release = asyncio.Event()

    async def held() -> str:
        await release.wait()
        return "ok"

    tasks = [asyncio.create_task(bulkhead.call(held)) for _ in range(2)]
    await settle()
    assert bulkhead.in_flight == 2
    assert value("resilience_bulkhead_in_flight", name="b-full") == 2
    with pytest.raises(BulkheadFullError) as info:
        await bulkhead.call(held)
    assert info.value.reason == "full"
    release.set()
    assert await asyncio.gather(*tasks) == ["ok", "ok"]
    assert bulkhead.in_flight == 0
    assert value("resilience_bulkhead_rejected_total", name="b-full", reason="full") == 1


async def test_queue_admits_waiters_up_to_its_size_and_drains_in_order() -> None:
    bulkhead = Bulkhead("b-queue", max_concurrent=1, max_queue=2, queue_timeout=60.0)
    gates = [asyncio.Event() for _ in range(3)]
    order: list[int] = []

    async def work(index: int) -> int:
        order.append(index)
        await gates[index].wait()
        return index

    tasks = [asyncio.create_task(bulkhead.call(lambda i=i: work(i))) for i in range(3)]
    await settle()
    assert bulkhead.queued == 2 and value("resilience_bulkhead_queued", name="b-queue") == 2
    with pytest.raises(BulkheadFullError):
        await bulkhead.call(lambda: work(0))
    for gate in gates:
        gate.set()
    assert await asyncio.gather(*tasks) == [0, 1, 2]
    assert order == [0, 1, 2] and bulkhead.queued == 0


async def test_queue_timeout_rejects_and_frees_the_queue_position() -> None:
    clock = FakeClock()

    async def expired_waiter(awaitable, timeout):  # type: ignore[no-untyped-def]
        task = asyncio.ensure_future(awaitable)
        await asyncio.sleep(0)
        clock.advance(timeout)
        task.cancel()
        raise TimeoutError

    bulkhead = Bulkhead(
        "b-timeout",
        max_concurrent=1,
        max_queue=1,
        queue_timeout=0.5,
        clock=clock,
        waiter=expired_waiter,
    )
    release = asyncio.Event()

    async def held() -> None:
        await release.wait()

    running = asyncio.create_task(bulkhead.call(held))
    await settle()
    with pytest.raises(BulkheadFullError) as info:
        await bulkhead.call(held)
    assert info.value.reason == "timeout" and bulkhead.queued == 0
    assert value("resilience_bulkhead_rejected_total", name="b-timeout", reason="timeout") == 1
    assert value("resilience_bulkhead_wait_seconds_sum", name="b-timeout") == pytest.approx(0.5)
    release.set()
    await running
    assert bulkhead.in_flight == 0


async def test_slot_is_released_when_the_call_fails() -> None:
    bulkhead = Bulkhead("b-error", max_concurrent=1)

    @bulkhead.protect
    async def boom() -> None:
        raise RuntimeError

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await boom()
    assert bulkhead.in_flight == 0
    async with bulkhead.slot():
        assert bulkhead.in_flight == 1


async def test_cancelled_waiter_does_not_leak_queue_or_slots() -> None:
    bulkhead = Bulkhead("b-cancel", max_concurrent=1, max_queue=1, queue_timeout=60.0)
    release = asyncio.Event()

    async def held() -> None:
        await release.wait()

    running = asyncio.create_task(bulkhead.call(held))
    await settle()
    waiter = asyncio.create_task(bulkhead.call(held))
    await settle()
    assert bulkhead.queued == 1
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert bulkhead.queued == 0
    release.set()
    await running
    await bulkhead.call(held)


@pytest.mark.parametrize("bad", [{"max_concurrent": 0}, {"max_queue": -1}, {"queue_timeout": -1}])
def test_invalid_configuration(bad: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        Bulkhead("b-bad", **bad)  # type: ignore[arg-type]
