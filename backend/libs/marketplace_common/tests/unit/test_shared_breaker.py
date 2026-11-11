from __future__ import annotations

import pytest

from marketplace_common.resilience import BreakerConfig, BreakerState, CircuitOpenError
from marketplace_common.resilience.shared_breaker import SharedCircuitBreaker
from tests.unit.fakes import FakeClock


class Boom(Exception):
    pass


class FakeRedis:
    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self.expires: dict[str, float] = {}
        self.down = False
        self.reads = 0

    async def set(self, key: str, value: str, px: int | None = None) -> bool:
        if self.down:
            raise ConnectionError("down")
        self.expires[key] = self._clock() + (px or 10**9) / 1000
        return True

    async def pttl(self, key: str) -> int:
        self.reads += 1
        if self.down:
            raise ConnectionError("down")
        left = self.expires.get(key, 0) - self._clock()
        return int(left * 1000) if left > 0 else -2

    async def delete(self, key: str) -> int:
        if self.down:
            raise ConnectionError("down")
        return 1 if self.expires.pop(key, None) is not None else 0


CONFIG = BreakerConfig(minimum_calls=4, window_size=10, open_seconds=10.0, half_open_max_calls=2)


def replica(clock: FakeClock, redis: FakeRedis, name: str = "catalog") -> SharedCircuitBreaker:
    return SharedCircuitBreaker(name, CONFIG, redis, clock=clock, sync_interval=0.0)


async def fail() -> str:
    raise Boom


async def ok() -> str:
    return "ok"


async def trip(breaker: SharedCircuitBreaker) -> None:
    for _ in range(4):
        with pytest.raises(Boom):
            await breaker.call(fail)


async def test_a_replica_that_saw_no_failure_opens_when_another_one_trips() -> None:
    clock = FakeClock()
    redis = FakeRedis(clock)
    one, two = replica(clock, redis), replica(clock, redis)
    await trip(one)
    assert one.state is BreakerState.OPEN

    called = False

    async def operation() -> str:
        nonlocal called
        called = True
        return "ok"

    with pytest.raises(CircuitOpenError) as error:
        await two.call(operation)
    assert not called
    assert two.state is BreakerState.OPEN
    assert error.value.retry_after_seconds == pytest.approx(10.0, abs=0.1)


async def test_the_replicas_reopen_window_matches_the_remaining_time() -> None:
    clock = FakeClock()
    redis = FakeRedis(clock)
    one, two = replica(clock, redis), replica(clock, redis)
    await trip(one)
    clock.advance(6)
    with pytest.raises(CircuitOpenError) as error:
        await two.call(ok)
    assert error.value.retry_after_seconds == pytest.approx(4.0, abs=0.2)
    clock.advance(4.5)
    assert two.state is BreakerState.HALF_OPEN


async def test_recovery_closes_the_shared_flag_so_nobody_reopens() -> None:
    clock = FakeClock()
    redis = FakeRedis(clock)
    one, two = replica(clock, redis), replica(clock, redis)
    await trip(one)
    clock.advance(11)
    for _ in range(2):
        assert await one.call(ok) == "ok"
    assert one.state is BreakerState.CLOSED
    assert await two.call(ok) == "ok"
    assert two.state is BreakerState.CLOSED


async def test_a_failed_probe_reopens_for_everyone() -> None:
    clock = FakeClock()
    redis = FakeRedis(clock)
    one, two = replica(clock, redis), replica(clock, redis)
    await trip(one)
    clock.advance(11)
    with pytest.raises(Boom):
        await one.call(fail)
    with pytest.raises(CircuitOpenError):
        await two.call(ok)


async def test_breakers_with_different_names_do_not_interfere() -> None:
    clock = FakeClock()
    redis = FakeRedis(clock)
    await trip(replica(clock, redis, "catalog"))
    assert await replica(clock, redis, "ordering").call(ok) == "ok"


async def test_redis_down_degrades_to_the_local_breaker() -> None:
    clock = FakeClock()
    redis = FakeRedis(clock)
    redis.down = True
    one, two = replica(clock, redis), replica(clock, redis)
    await trip(one)
    assert one.state is BreakerState.OPEN
    assert await two.call(ok) == "ok"


async def test_the_shared_flag_is_polled_at_most_once_per_interval() -> None:
    clock = FakeClock()
    redis = FakeRedis(clock)
    breaker = SharedCircuitBreaker("catalog", CONFIG, redis, clock=clock, sync_interval=1.0)
    for _ in range(5):
        await breaker.call(ok)
    assert redis.reads == 1
    clock.advance(1.1)
    await breaker.call(ok)
    assert redis.reads == 2
