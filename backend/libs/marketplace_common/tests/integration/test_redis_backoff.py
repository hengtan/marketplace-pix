import asyncio
import os
import uuid

import pytest
from redis.asyncio import Redis

from marketplace_common.resilience import RatePolicy, RedisTokenBucket, RouteRateLimiter
from marketplace_common.security.backoff import ProgressiveBackoff

REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/15")


@pytest.fixture
async def redis():  # type: ignore[no-untyped-def]
    client = Redis.from_url(REDIS_URL)
    try:
        await client.ping()
    except Exception:
        pytest.skip("redis not available")
    yield client
    await client.aclose()


async def test_two_instances_share_the_backoff_state(redis: Redis) -> None:
    prefix = f"test-{uuid.uuid4().hex}:"
    one = ProgressiveBackoff(redis, prefix=prefix, base_seconds=1.0, max_seconds=8.0)
    two = ProgressiveBackoff(redis, prefix=prefix, base_seconds=1.0, max_seconds=8.0)
    assert await one.record_failure("ip|user") == 1.0
    assert await two.record_failure("ip|user") == 2.0
    assert 0 < await one.blocked_for("ip|user") <= 2.0
    await asyncio.sleep(2.1)
    assert await two.blocked_for("ip|user") == 0
    await one.reset("ip|user")
    assert await two.record_failure("ip|user") == 1.0


async def test_two_limiters_share_one_bucket_per_key(redis: Redis) -> None:
    prefix = f"test-{uuid.uuid4().hex}"
    policy = {"login": RatePolicy(capacity=3, refill_per_second=0.001)}

    def limiter() -> RouteRateLimiter:
        return RouteRateLimiter(
            RatePolicy(1000, 1000.0), policy, primary=RedisTokenBucket(redis, prefix=prefix)
        )

    first, second = limiter(), limiter()
    decisions = [
        await (first if n % 2 == 0 else second).acquire("login", "1.2.3.4|abc") for n in range(5)
    ]
    assert [d.allowed for d in decisions] == [True, True, True, False, False]
