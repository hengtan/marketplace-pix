from __future__ import annotations

import pytest

from marketplace_common.security.backoff import ProgressiveBackoff
from tests.unit.fakes import FakeClock


class FakeRedis:
    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self.values: dict[str, int] = {}
        self.expires: dict[str, float] = {}
        self.down = False

    def _alive(self, key: str) -> bool:
        if key in self.expires and self.expires[key] <= self._clock():
            self.values.pop(key, None)
            self.expires.pop(key, None)
        return key in self.values

    async def incr(self, key: str) -> int:
        if self.down:
            raise ConnectionError("down")
        self._alive(key)
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.expires[key] = self._clock() + seconds
        return True

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        if self.down:
            raise ConnectionError("down")
        self.values[key] = 1
        if ex is not None:
            self.expires[key] = self._clock() + ex
        return True

    async def pttl(self, key: str) -> int:
        if self.down:
            raise ConnectionError("down")
        if not self._alive(key):
            return -2
        return int((self.expires[key] - self._clock()) * 1000)

    async def delete(self, *keys: str) -> int:
        if self.down:
            raise ConnectionError("down")
        return sum(1 for key in keys if self.values.pop(key, None) is not None)


@pytest.fixture(params=["memory", "redis"])
def backoff(request: pytest.FixtureRequest) -> tuple[ProgressiveBackoff, FakeClock]:
    clock = FakeClock(start=1000.0)
    redis = FakeRedis(clock) if request.param == "redis" else None
    return ProgressiveBackoff(redis, base_seconds=2.0, max_seconds=30.0, clock=clock), clock


async def test_each_failure_doubles_the_wait_up_to_the_cap(backoff) -> None:
    guard, clock = backoff
    delays = []
    for _ in range(6):
        delays.append(await guard.record_failure("k"))
        clock.advance(guard_wait(delays[-1]))
    assert delays == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0]


def guard_wait(delay: float) -> float:
    return delay + 0.01


async def test_the_key_is_blocked_for_the_remaining_delay(backoff) -> None:
    guard, clock = backoff
    assert await guard.blocked_for("k") == 0
    await guard.record_failure("k")
    assert await guard.blocked_for("k") == pytest.approx(2.0, abs=0.1)
    clock.advance(1.5)
    assert await guard.blocked_for("k") == pytest.approx(0.5, abs=0.1)
    clock.advance(0.6)
    assert await guard.blocked_for("k") == 0
    assert await guard.blocked_for("other") == 0


async def test_success_resets_the_progression(backoff) -> None:
    guard, clock = backoff
    await guard.record_failure("k")
    clock.advance(3)
    await guard.record_failure("k")
    await guard.reset("k")
    assert await guard.blocked_for("k") == 0
    assert await guard.record_failure("k") == 2.0


async def test_the_failure_count_is_forgotten_after_the_memory_window(backoff) -> None:
    guard, clock = backoff
    await guard.record_failure("k")
    clock.advance(10_000)
    assert await guard.record_failure("k") == 2.0


async def test_redis_failures_fall_back_to_process_memory() -> None:
    clock = FakeClock(start=1000.0)
    redis = FakeRedis(clock)
    redis.down = True
    guard = ProgressiveBackoff(redis, base_seconds=2.0, clock=clock)
    assert await guard.record_failure("k") == 2.0
    assert await guard.blocked_for("k") == pytest.approx(2.0, abs=0.1)
    assert await guard.record_failure("k") == 4.0
