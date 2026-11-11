import asyncio

import pytest
from prometheus_client import REGISTRY

from marketplace_common.resilience import (
    BreakerConfig,
    BreakerRegistry,
    BreakerState,
    CircuitBreaker,
    CircuitOpenError,
)
from tests.unit.fakes import FakeClock


class Boom(Exception):
    pass


def metric(metric_name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(metric_name, labels) or 0.0


async def ok() -> str:
    return "ok"


async def fail() -> str:
    raise Boom


def make(clock: FakeClock, name: str, **overrides: object) -> CircuitBreaker:
    config = BreakerConfig(
        **{
            "minimum_calls": 4,
            "window_size": 10,
            "window_seconds": 30.0,
            "open_seconds": 10.0,
            "half_open_max_calls": 2,
            **overrides,
        }  # type: ignore[arg-type]
    )
    return CircuitBreaker(name, config, clock=clock)


async def trip(breaker: CircuitBreaker, failures: int = 4) -> None:
    for _ in range(failures):
        with pytest.raises(Boom):
            await breaker.call(fail)


async def test_stays_closed_below_minimum_calls() -> None:
    breaker = make(FakeClock(), "t-min")
    await trip(breaker, failures=3)
    assert breaker.state is BreakerState.CLOSED


async def test_opens_when_failure_rate_reaches_threshold() -> None:
    breaker = make(FakeClock(), "t-open")
    await trip(breaker)
    assert breaker.state is BreakerState.OPEN
    with pytest.raises(CircuitOpenError) as info:
        await breaker.call(ok)
    assert info.value.name == "t-open"
    assert 0 < info.value.retry_after_seconds <= 10.0


async def test_mixed_traffic_below_threshold_keeps_it_closed() -> None:
    breaker = make(FakeClock(), "t-mixed", failure_rate_threshold=0.6)
    for _ in range(3):
        await breaker.call(ok)
    await trip(breaker, failures=2)
    assert breaker.state is BreakerState.CLOSED
    snapshot = breaker.snapshot()
    assert snapshot["calls_in_window"] == 5 and snapshot["failure_rate"] == 0.4


async def test_old_calls_age_out_of_the_window() -> None:
    clock = FakeClock()
    breaker = make(clock, "t-age")
    await trip(breaker, failures=3)
    clock.advance(31)
    await trip(breaker, failures=1)
    assert breaker.state is BreakerState.CLOSED
    assert breaker.snapshot()["calls_in_window"] == 1


async def test_window_size_discards_the_oldest_calls() -> None:
    breaker = make(FakeClock(), "t-size", window_size=4, failure_rate_threshold=0.75)
    await trip(breaker, failures=2)
    for _ in range(4):
        await breaker.call(ok)
    assert breaker.snapshot()["failure_rate"] == 0.0
    assert breaker.state is BreakerState.CLOSED


async def test_slow_calls_open_the_circuit_even_without_errors() -> None:
    clock = FakeClock()
    breaker = make(clock, "t-slow", slow_call_threshold=1.0, slow_call_rate_threshold=0.5)

    async def slow() -> str:
        clock.advance(2.0)
        return "late"

    for _ in range(4):
        await breaker.call(slow)
    assert breaker.state is BreakerState.OPEN
    assert metric("resilience_circuit_breaker_calls_total", name="t-slow", outcome="slow") == 4


async def test_fast_calls_are_not_slow() -> None:
    clock = FakeClock()
    breaker = make(clock, "t-fast", slow_call_threshold=1.0)
    for _ in range(6):
        await breaker.call(ok)
    assert breaker.state is BreakerState.CLOSED


async def test_goes_half_open_after_the_wait_and_closes_after_successful_probes() -> None:
    clock = FakeClock()
    breaker = make(clock, "t-recover")
    await trip(breaker)
    clock.advance(9.9)
    assert breaker.state is BreakerState.OPEN
    clock.advance(0.2)
    assert breaker.state is BreakerState.HALF_OPEN
    await breaker.call(ok)
    assert breaker.state is BreakerState.HALF_OPEN
    await breaker.call(ok)
    assert breaker.state is BreakerState.CLOSED
    assert breaker.snapshot()["calls_in_window"] == 0


async def test_one_failed_probe_reopens_and_restarts_the_wait() -> None:
    clock = FakeClock()
    breaker = make(clock, "t-reopen")
    await trip(breaker)
    clock.advance(10)
    with pytest.raises(Boom):
        await breaker.call(fail)
    assert breaker.state is BreakerState.OPEN
    clock.advance(5)
    assert breaker.state is BreakerState.OPEN
    clock.advance(5)
    assert breaker.state is BreakerState.HALF_OPEN


async def test_half_open_limits_concurrent_probes() -> None:
    clock = FakeClock()
    breaker = make(clock, "t-probes", half_open_max_calls=2)
    await trip(breaker)
    clock.advance(10)
    release = asyncio.Event()

    async def held() -> str:
        await release.wait()
        return "ok"

    first = asyncio.create_task(breaker.call(held))
    second = asyncio.create_task(breaker.call(held))
    await asyncio.sleep(0)
    with pytest.raises(CircuitOpenError):
        await breaker.call(ok)
    release.set()
    assert await asyncio.gather(first, second) == ["ok", "ok"]
    assert breaker.state is BreakerState.CLOSED


async def test_cancelled_probe_frees_the_slot_without_counting() -> None:
    clock = FakeClock()
    breaker = make(clock, "t-cancel", half_open_max_calls=1)
    await trip(breaker)
    clock.advance(10)

    async def forever() -> str:
        await asyncio.Event().wait()
        return "never"

    task = asyncio.create_task(breaker.call(forever))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert breaker.state is BreakerState.HALF_OPEN
    await breaker.call(ok)
    assert breaker.state is BreakerState.CLOSED


async def test_ignored_exceptions_do_not_count_as_failures() -> None:
    class NotFound(Exception):
        pass

    clock = FakeClock()
    breaker = CircuitBreaker(
        "t-ignore",
        BreakerConfig(minimum_calls=2, window_size=4),
        clock=clock,
        is_failure=lambda e: not isinstance(e, NotFound),
    )

    async def missing() -> str:
        raise NotFound

    for _ in range(6):
        with pytest.raises(NotFound):
            await breaker.call(missing)
    assert breaker.state is BreakerState.CLOSED
    assert metric("resilience_circuit_breaker_calls_total", name="t-ignore", outcome="ignored") == 6


async def test_failure_on_result_counts_bad_responses() -> None:
    breaker = make(FakeClock(), "t-result")

    async def response() -> int:
        return 503

    for _ in range(4):
        assert await breaker.call(response, failure_on_result=lambda code: code >= 500) == 503
    assert breaker.state is BreakerState.OPEN


async def test_decorator_and_context_manager() -> None:
    breaker = make(FakeClock(), "t-deco")

    @breaker.protect
    async def decorated(value: int) -> int:
        if value < 0:
            raise Boom
        return value * 2

    assert await decorated(2) == 4
    for _ in range(3):
        with pytest.raises(Boom):
            await decorated(-1)
    with pytest.raises(CircuitOpenError):
        async with breaker.guard():
            pytest.fail("must not run")


async def test_metrics_track_state_transitions_and_rejections() -> None:
    clock = FakeClock()
    name = "t-metrics"
    breaker = make(clock, name)
    assert metric("resilience_circuit_breaker_state", name=name, state="closed") == 1
    await trip(breaker)
    for _ in range(3):
        with pytest.raises(CircuitOpenError):
            await breaker.call(ok)
    assert metric("resilience_circuit_breaker_state", name=name, state="open") == 1
    assert metric("resilience_circuit_breaker_state", name=name, state="closed") == 0
    assert metric("resilience_circuit_breaker_rejected_total", name=name) == 3
    clock.advance(10)
    await breaker.call(ok)
    await breaker.call(ok)
    transitions = "resilience_circuit_breaker_transitions_total"
    assert metric(transitions, name=name, from_state="closed", to_state="open") == 1
    assert metric(transitions, name=name, from_state="open", to_state="half_open") == 1
    assert metric(transitions, name=name, from_state="half_open", to_state="closed") == 1
    assert metric("resilience_circuit_breaker_calls_total", name=name, outcome="failure") == 4


async def test_late_result_after_opening_does_not_corrupt_state() -> None:
    clock = FakeClock()
    breaker = make(clock, "t-late")
    release = asyncio.Event()

    async def held() -> str:
        await release.wait()
        return "ok"

    pending = asyncio.create_task(breaker.call(held))
    await asyncio.sleep(0)
    await trip(breaker)
    assert breaker.state is BreakerState.OPEN
    release.set()
    await pending
    assert breaker.state is BreakerState.OPEN


def test_registry_reuses_breakers_and_reports_snapshots() -> None:
    registry = BreakerRegistry(clock=FakeClock())
    assert registry.get("t-reg") is registry.get("t-reg")
    assert registry.snapshot()["t-reg"]["state"] == "closed"


@pytest.mark.parametrize(
    "bad",
    [
        {"failure_rate_threshold": 0},
        {"minimum_calls": 0},
        {"window_size": 1, "minimum_calls": 2},
        {"half_open_max_calls": 0},
        {"open_seconds": 0},
    ],
)
def test_invalid_configuration_is_rejected(bad: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        BreakerConfig(**bad)  # type: ignore[arg-type]
