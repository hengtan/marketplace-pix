from __future__ import annotations

from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from payments.infrastructure.db.models import InboxMessageModel


class SqlAlchemyInboxStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(self, message_id: UUID, consumer: str) -> bool:
        stmt = (
            insert(InboxMessageModel)
            .values(message_id=message_id, consumer=consumer)
            .on_conflict_do_nothing(index_elements=["message_id", "consumer"])
            .returning(InboxMessageModel.message_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None
