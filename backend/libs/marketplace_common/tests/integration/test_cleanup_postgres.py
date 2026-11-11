from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from marketplace_common.maintenance import (
    CleanupJob,
    CleanupTarget,
    RetentionPolicy,
    idempotency_target,
    inbox_target,
    outbox_target,
)
from tests.integration.pg import build_engine, ensure_database

DB = "marketplace_common_test"
SCHEMA = [
    "drop table if exists outbox_events, inbox_messages, idempotency_keys",
    "create table outbox_events (id uuid primary key, published_at timestamptz)",
    "create table inbox_messages (message_id uuid, consumer text, processed_at timestamptz,"
    " primary key (message_id, consumer))",
    "create table idempotency_keys (key text primary key, created_at timestamptz)",
]


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    await ensure_database(DB)
    engine = build_engine(DB)
    async with engine.begin() as conn:
        for statement in SCHEMA:
            await conn.execute(text(statement))
    yield engine
    await engine.dispose()


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def count(engine: AsyncEngine, table: str) -> int:
    async with engine.connect() as conn:
        return int(await conn.scalar(text(f"select count(*) from {table}")) or 0)


async def fill_outbox(engine: AsyncEngine, published_old: int, unpublished_old: int, recent: int):
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "insert into outbox_events select gen_random_uuid(), now() - interval '30 days'"
                " from generate_series(1, :n)"
            ),
            {"n": published_old},
        )
        await conn.execute(
            text(
                "insert into outbox_events select gen_random_uuid(), null"
                " from generate_series(1, :n)"
            ),
            {"n": unpublished_old},
        )
        await conn.execute(
            text(
                "insert into outbox_events select gen_random_uuid(), now() - interval '1 hour'"
                " from generate_series(1, :n)"
            ),
            {"n": recent},
        )


POLICY = RetentionPolicy(batch_size=1000, max_batches_per_run=50, pause_seconds=0.0)


async def test_only_published_rows_past_retention_are_removed(engine):
    await fill_outbox(engine, published_old=30, unpublished_old=7, recent=5)

    deleted = await CleanupJob(engine, [outbox_target(POLICY)], POLICY).run_once()

    assert deleted == {"outbox_published": 30}
    assert await count(engine, "outbox_events") == 12
    async with engine.connect() as conn:
        assert (
            await conn.scalar(text("select count(*) from outbox_events where published_at is null"))
            == 7
        )


async def test_large_tables_are_cleaned_in_bounded_batches_with_metrics(engine):
    await fill_outbox(engine, published_old=2500, unpublished_old=0, recent=10)
    batches_before = sample("marketplace_cleanup_batches_total", table="outbox_published")
    deleted_before = sample("marketplace_cleanup_deleted_total", table="outbox_published")

    deleted = await CleanupJob(engine, [outbox_target(POLICY)], POLICY).run_once()

    assert deleted["outbox_published"] == 2500
    assert await count(engine, "outbox_events") == 10
    assert (
        sample("marketplace_cleanup_batches_total", table="outbox_published") - batches_before == 3
    )
    assert (
        sample("marketplace_cleanup_deleted_total", table="outbox_published") - deleted_before
        == 2500
    )
    assert sample("marketplace_cleanup_last_success_timestamp_seconds") > 0


async def test_a_run_is_capped_and_the_next_run_continues(engine):
    await fill_outbox(engine, published_old=2500, unpublished_old=0, recent=0)
    capped = RetentionPolicy(batch_size=1000, max_batches_per_run=2, pause_seconds=0.0)
    job = CleanupJob(engine, [outbox_target(capped)], capped)

    assert (await job.run_once())["outbox_published"] == 2000
    assert (await job.run_once())["outbox_published"] == 500
    assert (await job.run_once())["outbox_published"] == 0


async def test_rows_locked_by_another_transaction_are_skipped_not_waited_on(engine):
    await fill_outbox(engine, published_old=20, unpublished_old=0, recent=0)
    holder = await engine.connect()
    await holder.execute(text("begin"))
    await holder.execute(
        text("select id from outbox_events where published_at is not null limit 5 for update")
    )
    job = CleanupJob(engine, [outbox_target(POLICY)], POLICY)

    async with asyncio.timeout(5):
        deleted = await job.run_once()
    assert deleted["outbox_published"] == 15
    assert await count(engine, "outbox_events") == 5

    await holder.execute(text("rollback"))
    await holder.close()
    assert (await job.run_once())["outbox_published"] == 5
    assert await count(engine, "outbox_events") == 0


async def test_writers_are_not_blocked_while_a_big_cleanup_runs(engine):
    await fill_outbox(engine, published_old=6000, unpublished_old=0, recent=0)
    slow = RetentionPolicy(batch_size=500, max_batches_per_run=50, pause_seconds=0.02)
    job = CleanupJob(engine, [outbox_target(slow)], slow)
    worst = 0.0

    async def writer() -> None:
        nonlocal worst
        for _ in range(30):
            started = asyncio.get_running_loop().time()
            async with engine.begin() as conn:
                await conn.execute(
                    text("insert into outbox_events values (:id, null)"), {"id": uuid4()}
                )
            worst = max(worst, asyncio.get_running_loop().time() - started)
            await asyncio.sleep(0.01)

    await asyncio.gather(job.run_once(), writer())

    assert worst < 0.5
    assert await count(engine, "outbox_events") == 30


async def test_inbox_composite_key_and_idempotency_keys(engine):
    async with engine.begin() as conn:
        for consumer in ("a", "b"):
            await conn.execute(
                text(
                    "insert into inbox_messages"
                    " values (gen_random_uuid(), :c, now() - interval '30 days')"
                ),
                {"c": consumer},
            )
        shared = uuid4()
        await conn.execute(
            text(
                "insert into inbox_messages values (:m, 'a', now()),"
                " (:m, 'b', now() - interval '30 days')"
            ),
            {"m": shared},
        )
        await conn.execute(
            text(
                "insert into idempotency_keys values ('old', now() - interval '10 days'),"
                " ('new', now())"
            )
        )
    targets = [inbox_target(POLICY), idempotency_target(POLICY)]

    deleted = await CleanupJob(engine, targets, POLICY).run_once()

    assert deleted == {"inbox": 3, "idempotency_keys": 1}
    assert await count(engine, "inbox_messages") == 1
    async with engine.connect() as conn:
        assert await conn.scalar(text("select key from idempotency_keys")) == "new"


async def test_policy_controls_what_counts_as_expired(engine):
    async with engine.begin() as conn:
        await conn.execute(
            text("insert into idempotency_keys values ('k', now() - interval '3 hours')")
        )
    short = RetentionPolicy.from_env({"RETENTION_IDEMPOTENCY_HOURS": "2"})
    long = RetentionPolicy.from_env({"RETENTION_IDEMPOTENCY_HOURS": "6"})

    assert (await CleanupJob(engine, [idempotency_target(long)], long).run_once()) == {
        "idempotency_keys": 0
    }
    assert (await CleanupJob(engine, [idempotency_target(short)], short).run_once()) == {
        "idempotency_keys": 1
    }


async def test_run_forever_survives_errors_and_counts_them(engine):
    broken = CleanupTarget("ghost", "table_that_does_not_exist", "created_at", 60.0)
    fast = RetentionPolicy(interval_seconds=0.05, pause_seconds=0.0)
    job = CleanupJob(engine, [broken], fast)
    errors_before = sample("marketplace_cleanup_runs_total", result="error")
    stop = asyncio.Event()

    task = asyncio.create_task(job.run_forever(stop))
    await asyncio.sleep(0.4)
    stop.set()
    await task

    assert sample("marketplace_cleanup_runs_total", result="error") - errors_before >= 2


def test_unsafe_identifiers_and_non_positive_retention_are_rejected():
    with pytest.raises(ValueError):
        CleanupTarget("x", "outbox_events; drop table users", "created_at", 60.0)
    with pytest.raises(ValueError):
        CleanupTarget("x", "outbox_events", "created_at or 1=1", 60.0)
    with pytest.raises(ValueError):
        CleanupTarget("x", "outbox_events", "created_at", 0)


def test_policy_reads_the_environment_with_sane_defaults():
    default = RetentionPolicy.from_env({})
    assert default.outbox_published.days == 7 and default.inbox.days == 14
    custom = RetentionPolicy.from_env(
        {"RETENTION_INBOX_HOURS": "1", "CLEANUP_BATCH_SIZE": "10", "CLEANUP_INTERVAL_SECONDS": "7"}
    )
    assert custom.inbox.total_seconds() == 3600
    assert (custom.batch_size, custom.interval_seconds) == (10, 7.0)
