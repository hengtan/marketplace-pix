from datetime import UTC, datetime, timedelta
from uuid import uuid4

from marketplace_common.maintenance import CleanupJob, RetentionPolicy, inbox_target
from sqlalchemy import func, select

from notifications.infrastructure.db.models import InboxMessageModel

POLICY = RetentionPolicy(pause_seconds=0.0)


async def test_expired_inbox_rows_are_removed(engine, session_factory):
    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add_all(
            [
                InboxMessageModel(
                    message_id=uuid4(), consumer="c", processed_at=now - timedelta(days=30)
                ),
                InboxMessageModel(message_id=uuid4(), consumer="c", processed_at=now),
            ]
        )
        await session.commit()

    deleted = await CleanupJob(engine, [inbox_target(POLICY)], POLICY).run_once()

    assert deleted == {"inbox": 1}
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(InboxMessageModel)) == 1
