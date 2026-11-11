from __future__ import annotations

import os
import uuid

import httpx
import pytest
from redis.asyncio import Redis

from gateway.app import create_app
from tests.test_gateway import Recorder, settings

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


async def replica(handler: Recorder, prefix: str, **extra: object) -> httpx.AsyncClient:
    options: dict[str, object] = {
        "redis_url": REDIS_URL,
        "breaker_shared_state": True,
        "breaker_shared_prefix": prefix,
        "breaker_minimum_calls": 3,
        "breaker_window_size": 5,
        "rate_limit_per_minute": 0,
        "retry_attempts": 1,
        **extra,
    }
    cfg = settings(**options)
    app = create_app(cfg, transport=httpx.MockTransport(handler))
    await app.router.lifespan_context(app).__aenter__()
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw")


async def test_with_the_flag_two_gateway_instances_converge_on_an_open_breaker(redis) -> None:  # type: ignore[no-untyped-def]
    prefix = f"test-{uuid.uuid4().hex}:"
    broken = Recorder(httpx.Response(500, json={"detail": "boom"}))
    healthy = Recorder()
    one = await replica(broken, prefix)
    two = await replica(healthy, prefix)

    for _ in range(3):
        assert (await one.get("/api/catalog/products")).status_code == 500
    assert (await one.get("/api/catalog/products")).status_code == 503

    response = await two.get("/api/catalog/products")
    assert response.status_code == 503
    assert response.json()["code"] == "circuit_open"
    assert healthy.requests == []
    health = await two.get("/api/health")
    assert health.json()["breakers"]["catalog"]["state"] == "open"


async def test_without_the_flag_each_instance_keeps_its_own_state(redis) -> None:  # type: ignore[no-untyped-def]
    prefix = f"test-{uuid.uuid4().hex}:"
    broken = Recorder(httpx.Response(500, json={"detail": "boom"}))
    healthy = Recorder()
    one = await replica(broken, prefix, breaker_shared_state=False)
    two = await replica(healthy, prefix, breaker_shared_state=False)
    for _ in range(4):
        await one.get("/api/catalog/products")
    assert (await two.get("/api/catalog/products")).status_code == 200
    assert len(healthy.requests) == 1
