from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ordering.application.ports import IdempotencyRecord
from ordering.infrastructure.db.models import IdempotencyKeyModel


class SqlAlchemyIdempotencyStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(self, key: str, request_hash: str, order_id: UUID) -> IdempotencyRecord | None:
        stmt = (
            insert(IdempotencyKeyModel)
            .values(key=key, request_hash=request_hash, order_id=order_id)
            .on_conflict_do_nothing(index_elements=["key"])
            .returning(IdempotencyKeyModel.key)
        )
        claimed = (await self._session.execute(stmt)).scalar_one_or_none()
        if claimed is not None:
            return None
        row = (
            await self._session.execute(
                select(IdempotencyKeyModel).where(IdempotencyKeyModel.key == key)
            )
        ).scalar_one()
        return IdempotencyRecord(row.key, row.request_hash, row.order_id)
