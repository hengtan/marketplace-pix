import asyncio
import os
import uuid

import pytest
from redis.asyncio import Redis

from marketplace_common.security.revocation import RedisAccessTokenRevocations, RevocationChecker

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


async def test_revocation_has_a_ttl_and_is_visible_within_the_cache_window(redis: Redis) -> None:
    prefix = f"test-{uuid.uuid4().hex}:"
    writer = RedisAccessTokenRevocations(redis, prefix=prefix)
    checker = RevocationChecker(redis, prefix=prefix, cache_seconds=0.3)
    jti = uuid.uuid4().hex
    assert not await checker.is_revoked(jti)
    await writer.revoke(jti, 2)
    assert 0 < await redis.pttl(f"{prefix}{jti}") <= 2000
    await asyncio.sleep(0.4)
    assert await checker.is_revoked(jti)


async def test_the_entry_disappears_with_the_token_lifetime(redis: Redis) -> None:
    prefix = f"test-{uuid.uuid4().hex}:"
    jti = uuid.uuid4().hex
    await RedisAccessTokenRevocations(redis, prefix=prefix).revoke(jti, 1)
    await asyncio.sleep(1.3)
    assert await redis.exists(f"{prefix}{jti}") == 0
