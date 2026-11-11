from __future__ import annotations

from uuid import UUID

from marketplace_common.messaging import OutboxMessage
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from inventory.infrastructure.db.models import OutboxEventModel


class SqlAlchemyOutboxStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def fetch_pending(self, limit: int) -> list[OutboxMessage]:
        stmt = (
            select(OutboxEventModel)
            .where(OutboxEventModel.published_at.is_(None))
            .order_by(OutboxEventModel.created_at, OutboxEventModel.occurred_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [
            OutboxMessage(
                id=r.id,
                topic=r.topic,
                key=r.key,
                type=r.type,
                payload=r.payload,
                traceparent=r.traceparent,
            )
            for r in rows
        ]

    async def count_pending(self) -> int:
        stmt = (
            select(func.count())
            .select_from(OutboxEventModel)
            .where(OutboxEventModel.published_at.is_(None))
        )
        return int(await self._session.scalar(stmt) or 0)

    async def mark_published(self, ids: list[UUID]) -> None:
        await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.id.in_(ids))
            .values(published_at=func.now())
        )
