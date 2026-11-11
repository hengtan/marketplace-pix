from datetime import UTC, datetime, timedelta
from uuid import uuid4

from marketplace_common.maintenance import CleanupJob, RetentionPolicy, inbox_target, outbox_target
from sqlalchemy import func, select

from payments.infrastructure.db.models import InboxMessageModel, OutboxEventModel

POLICY = RetentionPolicy(batch_size=50, pause_seconds=0.0)


def outbox_row(published_at):
    order_id = uuid4()
    return OutboxEventModel(
        id=uuid4(),
        aggregate_id=order_id,
        topic="events",
        key=str(order_id),
        type="Anything",
        payload={},
        occurred_at=datetime.now(UTC),
        published_at=published_at,
    )


async def count(session_factory, model, *where):
    async with session_factory() as session:
        return await session.scalar(select(func.count()).select_from(model).where(*where))


async def test_expired_outbox_and_inbox_rows_are_removed_and_pending_events_stay(
    engine, session_factory
):
    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add_all(
            [
                outbox_row(now - timedelta(days=30)),
                outbox_row(now - timedelta(days=30)),
                outbox_row(now),
                outbox_row(None),
                InboxMessageModel(
                    message_id=uuid4(), consumer="c", processed_at=now - timedelta(days=30)
                ),
                InboxMessageModel(message_id=uuid4(), consumer="c", processed_at=now),
            ]
        )
        await session.commit()

    deleted = await CleanupJob(
        engine, [outbox_target(POLICY), inbox_target(POLICY)], POLICY
    ).run_once()

    assert deleted == {"outbox_published": 2, "inbox": 1}
    assert await count(session_factory, OutboxEventModel) == 2
    assert (
        await count(session_factory, OutboxEventModel, OutboxEventModel.published_at.is_(None)) == 1
    )
    assert await count(session_factory, InboxMessageModel) == 1
