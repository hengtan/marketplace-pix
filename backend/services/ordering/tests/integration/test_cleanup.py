from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from marketplace_common.maintenance import (
    CleanupJob,
    RetentionPolicy,
    idempotency_target,
    inbox_target,
    outbox_target,
)
from sqlalchemy import func, select

from ordering.infrastructure.db.models import (
    IdempotencyKeyModel,
    InboxMessageModel,
    OutboxEventModel,
)
from ordering.interface.api import create_app
from tests.fakes import FakeCatalog

POLICY = RetentionPolicy(
    outbox_published=timedelta(days=7),
    inbox=timedelta(days=14),
    idempotency_keys=timedelta(hours=48),
    batch_size=100,
    pause_seconds=0.0,
)


def targets():
    return [outbox_target(POLICY), inbox_target(POLICY), idempotency_target(POLICY)]


def outbox_row(published_at: datetime | None) -> OutboxEventModel:
    order_id = uuid4()
    return OutboxEventModel(
        id=uuid4(),
        aggregate_id=order_id,
        topic="orders.events",
        key=str(order_id),
        type="OrderPaid",
        payload={"order_id": str(order_id)},
        occurred_at=datetime.now(UTC),
        published_at=published_at,
    )


async def count(session_factory, model) -> int:
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model))


async def test_expired_rows_go_away_and_unpublished_or_recent_rows_stay(engine, session_factory):
    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add_all(
            [
                outbox_row(now - timedelta(days=30)),
                outbox_row(now - timedelta(days=8)),
                outbox_row(now - timedelta(days=1)),
                outbox_row(None),
                InboxMessageModel(
                    message_id=uuid4(), consumer="ordering", processed_at=now - timedelta(days=30)
                ),
                InboxMessageModel(message_id=uuid4(), consumer="ordering", processed_at=now),
                IdempotencyKeyModel(
                    key="old",
                    request_hash="h",
                    order_id=uuid4(),
                    created_at=now - timedelta(days=5),
                ),
                IdempotencyKeyModel(key="new", request_hash="h", order_id=uuid4(), created_at=now),
            ]
        )
        await session.commit()

    deleted = await CleanupJob(engine, targets(), POLICY).run_once()

    assert deleted == {"outbox_published": 2, "inbox": 1, "idempotency_keys": 1}
    assert await count(session_factory, OutboxEventModel) == 2
    async with session_factory() as session:
        pending = await session.scalar(
            select(func.count())
            .select_from(OutboxEventModel)
            .where(OutboxEventModel.published_at.is_(None))
        )
    assert pending == 1
    assert await count(session_factory, InboxMessageModel) == 1
    assert await count(session_factory, IdempotencyKeyModel) == 1


async def test_a_second_run_is_a_no_op_and_the_job_is_safe_to_run_twice_at_once(
    engine, session_factory
):
    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add_all([outbox_row(now - timedelta(days=30)) for _ in range(250)])
        await session.commit()
    job = CleanupJob(engine, targets(), POLICY)

    first, second = await asyncio.gather(job.run_once(), job.run_once())

    assert first["outbox_published"] + second["outbox_published"] == 250
    assert await count(session_factory, OutboxEventModel) == 0
    assert (await job.run_once())["outbox_published"] == 0


async def test_an_expired_idempotency_key_no_longer_replays_but_a_live_one_does(
    engine, session_factory, uow_factory
):
    product = uuid4()
    app = create_app(uow_factory=uow_factory, catalog=FakeCatalog({product: 1000}))
    body = {
        "customer_id": str(uuid4()),
        "customer_name": "Maria",
        "customer_email": "maria@example.com",
        "items": [{"product_id": str(product), "quantity": 1}],
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        first = await c.post("/orders", json=body, headers={"Idempotency-Key": "k"})
        live = await c.post("/orders", json=body, headers={"Idempotency-Key": "k"})
        assert live.json()["id"] == first.json()["id"]

        async with session_factory() as session:
            row = await session.get(IdempotencyKeyModel, "k")
            row.created_at = datetime.now(UTC) - timedelta(days=30)
            await session.commit()
        await CleanupJob(engine, [idempotency_target(POLICY)], POLICY).run_once()

        after = await c.post("/orders", json=body, headers={"Idempotency-Key": "k"})
    assert after.status_code == 201
    assert after.json()["id"] != first.json()["id"]
