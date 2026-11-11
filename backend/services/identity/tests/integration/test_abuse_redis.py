from __future__ import annotations

import os
import uuid

import httpx
import pytest
from marketplace_common.resilience import RedisTokenBucket, RouteRateLimiter
from marketplace_common.security import ClientIpResolver
from marketplace_common.security.backoff import ProgressiveBackoff
from redis.asyncio import Redis

from identity.application.abuse import AbuseGuard, AbusePolicy
from identity.application.auth import AuthPolicy, AuthService
from identity.interface.api import create_app
from tests.fakes import FakeHasher, FakeIssuer, FakeStore, FakeUow, MutableClock

REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/15")
PASSWORD = "correct horse battery"


@pytest.fixture
async def redis():  # type: ignore[no-untyped-def]
    client = Redis.from_url(REDIS_URL)
    try:
        await client.ping()
    except Exception:
        pytest.skip("redis not available")
    yield client
    await client.aclose()


def instance(redis: Redis, run: str, store: FakeStore, policy: AbusePolicy) -> httpx.AsyncClient:
    guard = AbuseGuard(
        RouteRateLimiter(
            policy.default_policy(),
            policy.route_policies(),
            primary=RedisTokenBucket(redis, prefix=f"{run}:rl"),
        ),
        ProgressiveBackoff(redis, prefix=f"{run}:bo:", base_seconds=1.0, max_seconds=4.0),
    )
    auth = AuthService(
        lambda: FakeUow(store), FakeHasher(), FakeIssuer(), AuthPolicy(), MutableClock()
    )
    app = create_app(
        auth=auth, jwks={"keys": []}, abuse_guard=guard, client_ips=ClientIpResolver([])
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("203.0.113.7", 1)), base_url="http://t"
    )


async def test_two_identity_instances_share_the_limit_and_the_backoff(redis: Redis) -> None:
    run = f"test-{uuid.uuid4().hex}"
    store = FakeStore()
    policy = AbusePolicy(login_per_minute_ip_email=4, login_per_minute_ip=100)
    one, two = instance(redis, run, store, policy), instance(redis, run, store, policy)
    await one.post(
        "/auth/register", json={"email": "ana@example.com", "name": "Ana", "password": PASSWORD}
    )
    good = {"email": "ana@example.com", "password": PASSWORD}
    codes = []
    for n in range(5):
        codes.append(
            (await (one if n % 2 == 0 else two).post("/auth/login", json=good)).status_code
        )
    assert codes == [200, 200, 200, 200, 429]

    run = f"test-{uuid.uuid4().hex}"
    one, two = instance(redis, run, store, policy), instance(redis, run, store, policy)
    bad = {"email": "ana@example.com", "password": "wrong password"}
    assert (await one.post("/auth/login", json=bad)).status_code == 401
    blocked = await two.post("/auth/login", json=good)
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "1"
