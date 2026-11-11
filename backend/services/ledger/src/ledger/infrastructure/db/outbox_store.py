from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ledger.application.ports import OutboxMessage
from ledger.infrastructure.db.models import OutboxEventModel


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
            OutboxMessage(id=r.id, topic=r.topic, key=r.key, type=r.type, payload=r.payload)
            for r in rows
        ]

    async def mark_published(self, ids: list[UUID]) -> None:
        await self._session.execute(
            update(OutboxEventModel)
            .where(OutboxEventModel.id.in_(ids))
            .values(published_at=func.now())
        )
