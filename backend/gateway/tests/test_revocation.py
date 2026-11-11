from __future__ import annotations

import asyncio
import os
import time
from typing import Any
from uuid import uuid4

import httpx
import jwt
import pytest
from marketplace_common.security.revocation import RedisAccessTokenRevocations, RevocationChecker
from redis.asyncio import Redis

from gateway.app import create_app
from tests.auth_helpers import Issuer, World
from tests.test_auth import bearer, make_settings

REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/15")


class MemoryRedis:
    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.down = False

    async def set(self, name: str, value: str, ex: int | None = None) -> bool:
        self.keys.add(name)
        return True

    async def exists(self, *names: str) -> int:
        if self.down:
            raise ConnectionError("redis down")
        return sum(name in self.keys for name in names)


async def gateway(world: World, revocations: Any, **settings: object) -> httpx.AsyncClient:
    app = create_app(
        make_settings(**settings),
        transport=httpx.MockTransport(world),
        revocations=revocations,
    )
    await app.router.lifespan_context(app).__aenter__()
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw")


def jti_of(token: str) -> str:
    return str(jwt.decode(token, options={"verify_signature": False})["jti"])


@pytest.fixture
def world() -> World:
    return World(Issuer())


async def test_a_revoked_access_token_gets_401_and_others_keep_working(world: World) -> None:
    redis = MemoryRedis()
    checker = RevocationChecker(redis, cache_seconds=0.0)
    client = await gateway(world, checker)
    mine, other = world.issuer.token(("customer",)), world.issuer.token(("customer",))
    assert (await client.get("/api/auth/me", headers=bearer(mine))).status_code == 200
    await RedisAccessTokenRevocations(redis).revoke(jti_of(mine), 60)
    revoked = await client.get("/api/auth/me", headers=bearer(mine))
    assert revoked.status_code == 401
    assert revoked.headers["www-authenticate"] == "Bearer"
    assert (await client.get("/api/auth/me", headers=bearer(other))).status_code == 200


async def test_a_revoked_token_is_also_refused_on_optional_routes(world: World) -> None:
    redis = MemoryRedis()
    client = await gateway(world, RevocationChecker(redis, cache_seconds=0.0))
    token = world.issuer.token(("customer",))
    await RedisAccessTokenRevocations(redis).revoke(jti_of(token), 60)
    response = await client.get(f"/api/orders/{uuid4()}", headers=bearer(token))
    assert response.status_code == 401
    assert world.upstream("ordering") == []


async def test_tokens_without_a_jti_are_rejected(world: World) -> None:
    client = await gateway(world, RevocationChecker(MemoryRedis()))
    now = int(time.time())
    bare = jwt.encode(
        {
            "iss": "marketplace-identity",
            "aud": "marketplace-api",
            "sub": str(uuid4()),
            "iat": now,
            "exp": now + 600,
        },
        world.issuer.private_key,
        algorithm="EdDSA",
        headers={"kid": world.issuer.kid},
    )
    assert (await client.get("/api/auth/me", headers=bearer(bare))).status_code == 401


async def test_redis_down_fails_open_by_default_and_closed_when_configured(world: World) -> None:
    redis = MemoryRedis()
    redis.down = True
    token = world.issuer.token(("customer",))
    open_client = await gateway(world, RevocationChecker(redis, fail_open=True))
    assert (await open_client.get("/api/auth/me", headers=bearer(token))).status_code == 200
    closed_client = await gateway(world, RevocationChecker(redis, fail_open=False))
    assert (await closed_client.get("/api/auth/me", headers=bearer(token))).status_code == 503
    assert (await closed_client.get("/api/catalog/products")).status_code == 200
    assert (await closed_client.get(f"/api/orders/{uuid4()}")).status_code == 200


@pytest.fixture
async def redis():  # type: ignore[no-untyped-def]
    client = Redis.from_url(REDIS_URL)
    try:
        await client.ping()
    except Exception:
        pytest.skip("redis not available")
    yield client
    await client.aclose()


async def test_with_real_redis_a_logout_cuts_the_token_in_under_a_second(
    world: World, redis: Redis
) -> None:
    client = await gateway(world, None, redis_url=REDIS_URL)
    token = world.issuer.token(("customer",))
    assert (await client.get("/api/auth/me", headers=bearer(token))).status_code == 200

    await RedisAccessTokenRevocations(redis).revoke(jti_of(token), 60)
    started = time.monotonic()
    status = 200
    while status == 200 and time.monotonic() - started < 1.0:
        status = (await client.get("/api/auth/me", headers=bearer(token))).status_code
        await asyncio.sleep(0.05)
    assert status == 401
    assert time.monotonic() - started < 1.0
    other = world.issuer.token(("customer",))
    assert (await client.get("/api/auth/me", headers=bearer(other))).status_code == 200
