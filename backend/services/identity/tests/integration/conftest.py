import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from identity.application.auth import AuthPolicy, AuthService
from identity.config import Settings
from identity.infrastructure.db.models import Base
from identity.infrastructure.db.uow import SqlAlchemyUnitOfWork
from identity.infrastructure.security.jwt_issuer import JwtAccessTokenIssuer
from identity.infrastructure.security.keys import load_signing_keys
from identity.infrastructure.security.password import Argon2idHasher

TEST_DB = "identity_test"


def _url(db: str) -> str:
    return Settings(identity_db=db).database_url


async def _ensure_test_database() -> None:
    admin = create_async_engine(_url("postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    async with admin.connect() as conn:
        exists = await conn.scalar(
            text("select 1 from pg_database where datname = :n"), {"n": TEST_DB}
        )
        if not exists:
            await conn.execute(text(f'create database "{TEST_DB}"'))
    await admin.dispose()


async def _reset_schema() -> None:
    engine = create_async_engine(_url(TEST_DB), poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def test_database() -> None:
    asyncio.run(_ensure_test_database())
    asyncio.run(_reset_schema())


@pytest.fixture
async def engine():
    engine: AsyncEngine = create_async_engine(_url(TEST_DB), poolclass=NullPool)
    yield engine
    async with engine.begin() as conn:
        await conn.execute(text("truncate users, refresh_tokens cascade"))
    await engine.dispose()


@pytest.fixture
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def auth(session_factory) -> AuthService:
    keys = load_signing_keys("", [], allow_ephemeral=True)
    return AuthService(
        lambda: SqlAlchemyUnitOfWork(session_factory),
        Argon2idHasher(time_cost=1, memory_kib=8, parallelism=1),
        JwtAccessTokenIssuer(keys, "iss", "aud"),
        AuthPolicy(max_failed_logins=3),
    )
