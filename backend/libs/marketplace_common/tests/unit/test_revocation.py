from __future__ import annotations

import pytest

from marketplace_common.security.revocation import (
    RedisAccessTokenRevocations,
    RevocationChecker,
    RevocationUnavailable,
)
from tests.unit.fakes import FakeClock


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, tuple[str, int]] = {}
        self.reads = 0
        self.down = False

    async def set(self, name: str, value: str, ex: int | None = None) -> bool:
        if self.down:
            raise ConnectionError("redis down")
        self.data[name] = (value, ex or 0)
        return True

    async def exists(self, *names: str) -> int:
        self.reads += 1
        if self.down:
            raise ConnectionError("redis down")
        return sum(1 for name in names if name in self.data)


async def test_a_revoked_jti_is_seen_and_an_unknown_one_is_not() -> None:
    redis = FakeRedis()
    writer = RedisAccessTokenRevocations(redis)
    await writer.revoke("abc", 120.4)
    checker = RevocationChecker(redis, cache_seconds=0.0)
    assert await checker.is_revoked("abc")
    assert not await checker.is_revoked("other")


async def test_the_ttl_is_the_remaining_life_rounded_up() -> None:
    redis = FakeRedis()
    await RedisAccessTokenRevocations(redis).revoke("abc", 120.4)
    (key,) = redis.data
    assert redis.data[key][1] == 121
    await RedisAccessTokenRevocations(redis).revoke("gone", 0)
    assert len(redis.data) == 1


async def test_negative_answers_are_cached_only_briefly() -> None:
    redis, clock = FakeRedis(), FakeClock(start=100.0)
    checker = RevocationChecker(redis, cache_seconds=0.5, clock=clock)
    assert not await checker.is_revoked("abc")
    assert not await checker.is_revoked("abc")
    assert redis.reads == 1
    await RedisAccessTokenRevocations(redis).revoke("abc", 60)
    assert not await checker.is_revoked("abc")
    clock.advance(0.6)
    assert await checker.is_revoked("abc")


async def test_a_positive_answer_is_remembered_without_asking_again() -> None:
    redis, clock = FakeRedis(), FakeClock(start=100.0)
    await RedisAccessTokenRevocations(redis).revoke("abc", 60)
    checker = RevocationChecker(redis, cache_seconds=0.5, clock=clock)
    assert await checker.is_revoked("abc")
    clock.advance(30)
    assert await checker.is_revoked("abc")
    assert redis.reads == 1


async def test_fail_open_accepts_the_token_and_does_not_hammer_redis() -> None:
    redis, clock = FakeRedis(), FakeClock(start=100.0)
    redis.down = True
    checker = RevocationChecker(
        redis, cache_seconds=0.5, fail_open=True, retry_after=2.0, clock=clock
    )
    assert not await checker.is_revoked("a")
    assert not await checker.is_revoked("b")
    assert redis.reads == 1
    redis.down = False
    clock.advance(2.1)
    await RedisAccessTokenRevocations(redis).revoke("c", 60)
    assert await checker.is_revoked("c")


async def test_fail_closed_refuses_while_redis_is_unavailable() -> None:
    redis, clock = FakeRedis(), FakeClock(start=100.0)
    redis.down = True
    checker = RevocationChecker(redis, fail_open=False, retry_after=2.0, clock=clock)
    with pytest.raises(RevocationUnavailable):
        await checker.is_revoked("a")
    with pytest.raises(RevocationUnavailable):
        await checker.is_revoked("b")
    assert redis.reads == 1


async def test_revoking_while_redis_is_down_raises_so_the_caller_can_decide() -> None:
    redis = FakeRedis()
    redis.down = True
    with pytest.raises(ConnectionError):
        await RedisAccessTokenRevocations(redis).revoke("abc", 60)


async def test_the_cache_is_bounded() -> None:
    redis = FakeRedis()
    checker = RevocationChecker(redis, cache_seconds=60, max_entries=10)
    for n in range(50):
        await checker.is_revoked(f"jti-{n}")
    assert checker.cached_entries <= 10
