from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from assistant.application.ports import SessionStore, StoredMessage
from assistant.infrastructure.db.models import MessageRow, SessionRow


class PgSessionStore(SessionStore):
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def ensure(self, session_id: UUID) -> datetime:
        async with self._factory.begin() as session:
            await session.execute(
                insert(SessionRow).values(id=session_id).on_conflict_do_nothing()
            )
            created = await session.scalar(
                select(SessionRow.created_at).where(SessionRow.id == session_id)
            )
        assert created is not None
        return created

    async def created_at(self, session_id: UUID) -> datetime | None:
        async with self._factory() as session:
            return await session.scalar(
                select(SessionRow.created_at).where(SessionRow.id == session_id)
            )

    async def append(
        self, session_id: UUID, role: str, content: str, meta: dict[str, Any]
    ) -> None:
        async with self._factory.begin() as session:
            session.add(MessageRow(session_id=session_id, role=role, content=content, meta=meta))

    async def messages(self, session_id: UUID, limit: int | None = None) -> list[StoredMessage]:
        stmt = select(MessageRow).where(MessageRow.session_id == session_id)
        if limit is None:
            stmt = stmt.order_by(MessageRow.id)
        else:
            stmt = stmt.order_by(MessageRow.id.desc()).limit(limit)
        async with self._factory() as session:
            rows = list((await session.scalars(stmt)).all())
        if limit is not None:
            rows.reverse()
        return [StoredMessage(r.role, r.content, r.created_at, r.meta) for r in rows]
