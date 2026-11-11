import asyncio
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from catalog.config import Settings
from catalog.infrastructure.db.repository import build_reader_factory
from catalog.interface.api import create_app
from catalog.seed import run_seed

TEST_DB = "catalog_test"
SERVICE_DIR = Path(__file__).resolve().parents[2]


def _url(db: str) -> str:
    return Settings(catalog_db=db).database_url


async def _ensure_test_database() -> None:
    admin = create_async_engine(_url("postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    async with admin.connect() as conn:
        exists = await conn.scalar(
            text("select 1 from pg_database where datname = :n"), {"n": TEST_DB}
        )
        if not exists:
            await conn.execute(text(f'create database "{TEST_DB}"'))
    await admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def test_database() -> None:
    asyncio.run(_ensure_test_database())
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=SERVICE_DIR,
        env={**os.environ, "CATALOG_DB": TEST_DB},
        check=True,
    )


@pytest.fixture
async def engine():
    engine: AsyncEngine = create_async_engine(_url(TEST_DB), poolclass=NullPool)
    yield engine
    async with engine.begin() as conn:
        await conn.execute(text("truncate products, categories, merchants, outbox_events cascade"))
    await engine.dispose()


@pytest.fixture
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def seeded(session_factory):
    await run_seed(session_factory)
    return session_factory


@pytest.fixture
async def client(seeded):
    app = create_app(reader_factory=build_reader_factory(seeded), cache_max_age=60)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
