from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ordering.infrastructure.db.idempotency import SqlAlchemyIdempotencyStore
from ordering.infrastructure.db.outbox import SqlAlchemyOutbox
from ordering.infrastructure.db.outbox_store import SqlAlchemyOutboxStore
from ordering.infrastructure.db.repositories import SqlAlchemyOrderRepository


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._orders: SqlAlchemyOrderRepository | None = None
        self._outbox: SqlAlchemyOutbox | None = None
        self._outbox_store: SqlAlchemyOutboxStore | None = None
        self._idempotency: SqlAlchemyIdempotencyStore | None = None

    @property
    def orders(self) -> SqlAlchemyOrderRepository:
        assert self._orders is not None, "use inside 'async with'"
        return self._orders

    @property
    def outbox(self) -> SqlAlchemyOutbox:
        assert self._outbox is not None, "use inside 'async with'"
        return self._outbox

    @property
    def idempotency(self) -> SqlAlchemyIdempotencyStore:
        assert self._idempotency is not None, "use inside 'async with'"
        return self._idempotency

    @property
    def outbox_store(self) -> SqlAlchemyOutboxStore:
        assert self._outbox_store is not None, "use inside 'async with'"
        return self._outbox_store

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self._orders = SqlAlchemyOrderRepository(self._session)
        self._outbox = SqlAlchemyOutbox(self._session)
        self._outbox_store = SqlAlchemyOutboxStore(self._session)
        self._idempotency = SqlAlchemyIdempotencyStore(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        assert self._session is not None
        try:
            if exc_type is not None:
                await self._session.rollback()
        finally:
            await self._session.close()

    async def commit(self) -> None:
        assert self._session is not None
        await self._session.commit()
