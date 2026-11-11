from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from identity.application.auth import AuthService
from identity.application.errors import (
    EmailAlreadyRegistered,
    InvalidCredentials,
    InvalidRefreshToken,
    RefreshTokenReuse,
)

PASSWORD = "correct horse battery"


async def test_register_login_and_refresh_against_postgres(auth: AuthService, engine) -> None:
    pair = await auth.register_customer("ana@example.com", "Ana", PASSWORD)
    async with engine.connect() as conn:
        stored = await conn.scalar(text("select password_hash from users"))
        token_hash = await conn.scalar(text("select token_hash from refresh_tokens"))
    assert stored.startswith("$argon2id$")
    assert token_hash != pair.refresh_token
    assert len(token_hash) == 64
    login = await auth.login("ana@example.com", PASSWORD)
    rotated = await auth.refresh(login.refresh_token)
    assert rotated.refresh_token != login.refresh_token


async def test_concurrent_duplicate_registration_creates_one_account(auth: AuthService) -> None:
    results = await asyncio.gather(
        *(auth.register_customer("race@example.com", "R", PASSWORD) for _ in range(8)),
        return_exceptions=True,
    )
    assert sum(1 for r in results if not isinstance(r, Exception)) == 1
    assert all(isinstance(r, EmailAlreadyRegistered) for r in results if isinstance(r, Exception))


async def test_concurrent_refresh_with_one_token_has_a_single_winner(
    auth: AuthService, engine
) -> None:
    pair = await auth.register_customer("ana@example.com", "Ana", PASSWORD)
    results = await asyncio.gather(
        *(auth.refresh(pair.refresh_token) for _ in range(6)), return_exceptions=True
    )
    winners = [r for r in results if not isinstance(r, Exception)]
    assert len(winners) == 1
    losers = [r for r in results if isinstance(r, Exception)]
    assert all(isinstance(r, InvalidRefreshToken) for r in losers)
    assert any(isinstance(r, RefreshTokenReuse) for r in losers)
    with pytest.raises(InvalidRefreshToken):
        await auth.refresh(winners[0].refresh_token)
    async with engine.connect() as conn:
        live = await conn.scalar(
            text("select count(*) from refresh_tokens where revoked_at is null")
        )
    assert live == 0


async def test_failed_logins_persist_and_lock_the_account(auth: AuthService, engine) -> None:
    await auth.register_customer("ana@example.com", "Ana", PASSWORD)
    for _ in range(3):
        with pytest.raises(InvalidCredentials):
            await auth.login("ana@example.com", "bad password!")
    async with engine.connect() as conn:
        locked = await conn.scalar(text("select locked_until is not null from users"))
    assert locked
    with pytest.raises(InvalidCredentials):
        await auth.login("ana@example.com", PASSWORD)


async def test_logout_revokes_only_that_session(auth: AuthService) -> None:
    await auth.register_customer("ana@example.com", "Ana", PASSWORD)
    phone = await auth.login("ana@example.com", PASSWORD)
    laptop = await auth.login("ana@example.com", PASSWORD)
    await auth.logout(phone.refresh_token)
    with pytest.raises(InvalidRefreshToken):
        await auth.refresh(phone.refresh_token)
    assert (await auth.refresh(laptop.refresh_token)).access_token


async def test_logout_and_reuse_put_the_real_access_token_on_the_redis_list(
    session_factory,
) -> None:
    import os
    from uuid import uuid4

    import jwt
    from marketplace_common.security.revocation import RedisAccessTokenRevocations
    from redis.asyncio import Redis

    from identity.application.auth import AuthPolicy, AuthService
    from identity.infrastructure.db.uow import SqlAlchemyUnitOfWork
    from identity.infrastructure.security.jwt_issuer import JwtAccessTokenIssuer
    from identity.infrastructure.security.keys import load_signing_keys
    from identity.infrastructure.security.password import Argon2idHasher

    redis = Redis.from_url(os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/15"))
    try:
        await redis.ping()
    except Exception:
        pytest.skip("redis not available")
    prefix = f"test-{uuid4().hex}:"
    auth = AuthService(
        lambda: SqlAlchemyUnitOfWork(session_factory),
        Argon2idHasher(time_cost=1, memory_kib=8, parallelism=1),
        JwtAccessTokenIssuer(load_signing_keys("", [], allow_ephemeral=True), "iss", "aud"),
        AuthPolicy(),
        revocations=RedisAccessTokenRevocations(redis, prefix=prefix),
    )

    def jti(token: str) -> str:
        return str(jwt.decode(token, options={"verify_signature": False})["jti"])

    try:
        await auth.register_customer("ana@example.com", "Ana", PASSWORD)
        first = await auth.login("ana@example.com", PASSWORD)
        assert await redis.exists(f"{prefix}{jti(first.access_token)}") == 0
        await auth.logout(first.refresh_token)
        key = f"{prefix}{jti(first.access_token)}"
        assert await redis.exists(key) == 1
        assert 0 < await redis.ttl(key) <= 610

        second = await auth.login("ana@example.com", PASSWORD)
        rotated = await auth.refresh(second.refresh_token)
        with pytest.raises(RefreshTokenReuse):
            await auth.refresh(second.refresh_token)
        for token in (second.access_token, rotated.access_token):
            assert await redis.exists(f"{prefix}{jti(token)}") == 1
    finally:
        await redis.aclose()
