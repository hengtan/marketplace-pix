from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from inventory.infrastructure.db.inbox import SqlAlchemyInboxStore
from inventory.infrastructure.db.outbox import SqlAlchemyOutbox
from inventory.infrastructure.db.outbox_store import SqlAlchemyOutboxStore
from inventory.infrastructure.db.repositories import (
    SqlAlchemyReservationRepository,
    SqlAlchemyStockRepository,
)


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._stocks: SqlAlchemyStockRepository | None = None
        self._reservations: SqlAlchemyReservationRepository | None = None
        self._outbox: SqlAlchemyOutbox | None = None
        self._outbox_store: SqlAlchemyOutboxStore | None = None
        self._inbox: SqlAlchemyInboxStore | None = None

    @property
    def stocks(self) -> SqlAlchemyStockRepository:
        assert self._stocks is not None, "use inside 'async with'"
        return self._stocks

    @property
    def reservations(self) -> SqlAlchemyReservationRepository:
        assert self._reservations is not None, "use inside 'async with'"
        return self._reservations

    @property
    def outbox(self) -> SqlAlchemyOutbox:
        assert self._outbox is not None, "use inside 'async with'"
        return self._outbox

    @property
    def outbox_store(self) -> SqlAlchemyOutboxStore:
        assert self._outbox_store is not None, "use inside 'async with'"
        return self._outbox_store

    @property
    def inbox(self) -> SqlAlchemyInboxStore:
        assert self._inbox is not None, "use inside 'async with'"
        return self._inbox

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self._stocks = SqlAlchemyStockRepository(self._session)
        self._reservations = SqlAlchemyReservationRepository(self._session)
        self._outbox = SqlAlchemyOutbox(self._session)
        self._outbox_store = SqlAlchemyOutboxStore(self._session)
        self._inbox = SqlAlchemyInboxStore(self._session)
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
