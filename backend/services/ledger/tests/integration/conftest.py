import asyncio

import pytest
from marketplace_common.observability import setup_tracing
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ledger.application.handle_order_event import HandleOrderEvent
from ledger.application.handle_payment_event import HandlePaymentEvent
from ledger.config import Settings
from ledger.infrastructure.db.models import Base
from ledger.infrastructure.db.uow import SqlAlchemyUnitOfWork

TEST_DB = "ledger_test"


def _url(db: str) -> str:
    return Settings(ledger_db=db).database_url


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
def tracing() -> None:
    setup_tracing("tests", span_exporter=InMemorySpanExporter())


@pytest.fixture(scope="session", autouse=True)
def test_database() -> None:
    asyncio.run(_ensure_test_database())
    asyncio.run(_reset_schema())


@pytest.fixture
async def engine():
    engine: AsyncEngine = create_async_engine(_url(TEST_DB), poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "truncate ledger_entries, ledger_transactions, accounts, order_projections, "
                "inbox_messages, outbox_events cascade"
            )
        )
    await engine.dispose()


@pytest.fixture
def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def uow_factory(session_factory):
    return lambda: SqlAlchemyUnitOfWork(session_factory)


@pytest.fixture
def order_handler(uow_factory):
    return HandleOrderEvent(uow_factory)


@pytest.fixture
def payment_handler(uow_factory):
    return HandlePaymentEvent(uow_factory)
