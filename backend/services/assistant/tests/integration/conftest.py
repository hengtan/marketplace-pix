import asyncio
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from assistant.config import Settings
from assistant.domain.models import CatalogProduct
from assistant.infrastructure.fixtures import (
    FixtureInventoryGateway,
    SnapshotCatalogGateway,
)
from assistant.interface.api import create_app
from assistant.wiring import Container, build_container

TEST_DB = "assistant_test"
SERVICE_DIR = Path(__file__).resolve().parents[2]
SNAPSHOT = SERVICE_DIR / "tests" / "fixtures" / "catalog.json"


def test_settings(**overrides: object) -> Settings:
    return Settings(assistant_db=TEST_DB, cache_enabled=False, **overrides)  # type: ignore[call-arg]


async def _ensure_test_database() -> None:
    admin = create_async_engine(
        test_settings().database_url.replace(f"/{TEST_DB}", "/postgres"),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
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
        env={**os.environ, "ASSISTANT_DB": TEST_DB},
        check=True,
    )


@pytest.fixture
def settings() -> Settings:
    return test_settings()


@pytest.fixture
async def engine(settings: Settings):
    engine: AsyncEngine = create_async_engine(settings.database_url, poolclass=NullPool)
    wipe = text("truncate chunks, sessions, messages, eval_runs, semantic_cache, llm_usage cascade")
    async with engine.begin() as conn:
        await conn.execute(wipe)
    yield engine
    async with engine.begin() as conn:
        await conn.execute(wipe)
    await engine.dispose()


class FakeOrders:
    def __init__(self) -> None:
        self.orders: dict[UUID, object] = {}

    async def get_order(self, order_id: UUID):  # type: ignore[no-untyped-def]
        return self.orders.get(order_id)


class MutableCatalog:
    def __init__(self, products: list[CatalogProduct]) -> None:
        self.products = products
        self._labels = SnapshotCatalogGateway(SNAPSHOT).labels

    async def list_products(self) -> list[CatalogProduct]:
        return list(self.products)

    async def get_product(self, product_id: UUID) -> CatalogProduct | None:
        return next((p for p in self.products if p.id == product_id), None)

    async def categories(self) -> dict[str, str]:
        return dict(self._labels)


@pytest.fixture
async def snapshot_products() -> list[CatalogProduct]:
    return await SnapshotCatalogGateway(SNAPSHOT).list_products()


@pytest.fixture
def catalog(snapshot_products: list[CatalogProduct]) -> MutableCatalog:
    return MutableCatalog(list(snapshot_products))


@pytest.fixture
def orders() -> FakeOrders:
    return FakeOrders()


@pytest.fixture
async def container(settings, engine, catalog, snapshot_products, orders) -> Container:
    built = build_container(
        settings,
        engine,
        catalog=catalog,
        inventory=FixtureInventoryGateway(snapshot_products),
        orders=orders,
        token_delay_seconds=0.0,
    )
    yield built
    await built.aclose()


@pytest.fixture
async def indexed(container: Container) -> Container:
    await container.ingest.execute()
    return container


@pytest.fixture
async def client(indexed: Container):
    app = create_app(container=indexed)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
