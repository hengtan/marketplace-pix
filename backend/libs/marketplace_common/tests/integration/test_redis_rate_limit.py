import os
import uuid

import pytest
from redis.asyncio import Redis

from marketplace_common.resilience import (
    InMemoryTokenBucket,
    RatePolicy,
    RedisFailureMode,
    RedisTokenBucket,
    RouteRateLimiter,
)
from tests.unit.fakes import FakeClock

REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/15")


@pytest.fixture
async def redis():  # type: ignore[no-untyped-def]
    client = Redis.from_url(REDIS_URL, max_connections=300)
    try:
        await client.ping()
    except Exception:
        pytest.skip("redis not available")
    yield client
    await client.aclose()


@pytest.fixture
def prefix() -> str:
    return f"test-{uuid.uuid4().hex}"


async def test_lua_token_bucket_burst_refill_and_ttl(redis: Redis, prefix: str) -> None:
    clock = FakeClock(start=1_000.0)
    bucket = RedisTokenBucket(redis, prefix=prefix, clock=clock)
    policy = RatePolicy(capacity=3, refill_per_second=1.0)
    decisions = [await bucket.take("c", policy) for _ in range(4)]
    assert [d.allowed for d in decisions] == [True, True, True, False]
    assert [d.remaining for d in decisions] == [2, 1, 0, 0]
    assert decisions[3].retry_after == pytest.approx(1.0)
    assert decisions[0].reset_after == pytest.approx(1.0)
    assert 0 < await redis.pttl(f"{prefix}:c") <= 4000
    clock.advance(1.0)
    assert (await bucket.take("c", policy)).allowed
    assert not (await bucket.take("c", policy)).allowed
    clock.advance(60.0)
    assert (await bucket.take("c", policy)).remaining == 2


async def test_lua_is_atomic_under_concurrency(redis: Redis, prefix: str) -> None:
    import asyncio

    bucket = RedisTokenBucket(redis, prefix=prefix, clock=FakeClock())
    policy = RatePolicy(capacity=25, refill_per_second=0.001)
    decisions = await asyncio.gather(*(bucket.take("c", policy) for _ in range(200)))
    assert sum(d.allowed for d in decisions) == 25


async def test_two_limiters_share_the_same_bucket(redis: Redis, prefix: str) -> None:
    policy = RatePolicy(capacity=4, refill_per_second=0.001)
    clock = FakeClock()
    a = RouteRateLimiter(policy, primary=RedisTokenBucket(redis, prefix=prefix, clock=clock))
    b = RouteRateLimiter(policy, primary=RedisTokenBucket(redis, prefix=prefix, clock=clock))
    results = [
        (await (a if i % 2 == 0 else b).acquire("orders", "client")).allowed for i in range(6)
    ]
    assert results == [True] * 4 + [False] * 2


async def test_server_clock_is_used_when_no_clock_is_injected(redis: Redis, prefix: str) -> None:
    import asyncio

    bucket = RedisTokenBucket(redis, prefix=prefix)
    policy = RatePolicy(capacity=1, refill_per_second=100.0)
    assert (await bucket.take("c", policy)).allowed
    assert not (await bucket.take("c", policy)).allowed
    await asyncio.sleep(0.05)
    assert (await bucket.take("c", policy)).allowed


async def test_route_limiter_falls_back_when_redis_is_unreachable() -> None:
    dead = Redis.from_url("redis://localhost:1/0", socket_connect_timeout=0.2)
    rl = RouteRateLimiter(
        RatePolicy(2, 0.001),
        primary=RedisTokenBucket(dead, prefix="x"),
        fallback=InMemoryTokenBucket(FakeClock()),
        on_failure=RedisFailureMode.FALLBACK,
        operation_timeout=1.0,
    )
    results = [(await rl.acquire("catalog", "c")).allowed for _ in range(3)]
    assert results == [True, True, False]
    await dead.aclose()
