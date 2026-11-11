import os
import uuid

import pytest
from redis.asyncio import Redis

from marketplace_common.resilience import BreakerConfig, CircuitOpenError
from marketplace_common.resilience.shared_breaker import SharedCircuitBreaker

REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/15")


class Boom(Exception):
    pass


@pytest.fixture
async def redis():  # type: ignore[no-untyped-def]
    client = Redis.from_url(REDIS_URL)
    try:
        await client.ping()
    except Exception:
        pytest.skip("redis not available")
    yield client
    await client.aclose()


async def test_two_instances_converge_through_a_real_redis(redis: Redis) -> None:
    prefix = f"test-{uuid.uuid4().hex}:"
    config = BreakerConfig(minimum_calls=3, window_size=5, open_seconds=1.0, half_open_max_calls=1)

    def instance() -> SharedCircuitBreaker:
        return SharedCircuitBreaker("catalog", config, redis, prefix=prefix, sync_interval=0.0)

    one, two = instance(), instance()

    async def fail() -> str:
        raise Boom

    async def ok() -> str:
        return "ok"

    for _ in range(3):
        with pytest.raises(Boom):
            await one.call(fail)
    with pytest.raises(CircuitOpenError):
        await two.call(ok)
    assert 0 < await redis.pttl(f"{prefix}catalog") <= 1000
