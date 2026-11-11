from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from marketplace_common.maintenance import CleanupJob, CleanupTarget, RetentionPolicy
from marketplace_common.observability import install_api_observability, instrument_sqlalchemy
from marketplace_common.security import PrincipalResolver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from identity.application.auth import AuthPolicy, AuthService
from identity.config import load_settings
from identity.infrastructure.db.session import build_engine, build_session_factory
from identity.infrastructure.db.uow import SqlAlchemyUnitOfWork
from identity.infrastructure.security.jwt_issuer import JwtAccessTokenIssuer
from identity.infrastructure.security.keys import load_signing_keys
from identity.infrastructure.security.password import Argon2idHasher
from identity.interface.api import ReadyCheck, create_app


def _db_check(engine: AsyncEngine) -> ReadyCheck:
    async def check() -> bool:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("select 1"))
        except Exception:
            return False
        return True

    return check


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()
    if settings.is_production and not settings.internal_auth_secret:
        raise RuntimeError("INTERNAL_AUTH_SECRET is required in production")
    engine = build_engine(settings.database_url)
    instrument_sqlalchemy(engine)
    factory = build_session_factory(engine)
    keys = load_signing_keys(
        settings.identity_signing_key,
        settings.identity_retired_public_keys,
        allow_ephemeral=not settings.is_production,
    )
    app.state.auth = AuthService(
        lambda: SqlAlchemyUnitOfWork(factory),
        Argon2idHasher(
            settings.argon2_time_cost, settings.argon2_memory_kib, settings.argon2_parallelism
        ),
        JwtAccessTokenIssuer(
            keys,
            settings.issuer,
            settings.audience,
            timedelta(seconds=settings.access_ttl_seconds),
        ),
        AuthPolicy(
            refresh_ttl=timedelta(days=settings.refresh_ttl_days),
            session_max=timedelta(days=settings.session_max_days),
            max_failed_logins=settings.max_failed_logins,
            lockout=timedelta(minutes=settings.lockout_minutes),
        ),
    )
    app.state.jwks = keys.jwks()
    app.state.principal_resolver = PrincipalResolver(settings.internal_auth_secret)
    app.state.ready_check = _db_check(engine)
    policy = RetentionPolicy(
        interval_seconds=settings.cleanup_interval_seconds, batch_size=settings.cleanup_batch_size
    )
    expired_tokens = CleanupTarget(
        "refresh_tokens",
        "refresh_tokens",
        "expires_at",
        timedelta(days=settings.refresh_retention_days).total_seconds(),
    )
    stop = asyncio.Event()
    cleanup = asyncio.create_task(CleanupJob(engine, [expired_tokens], policy).run_forever(stop))
    yield
    stop.set()
    await cleanup
    await engine.dispose()


app = create_app(lifespan=lifespan)
install_api_observability(app, "identity-api")
