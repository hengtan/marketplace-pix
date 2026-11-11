from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ledger.infrastructure.db.inbox import SqlAlchemyInboxStore
from ledger.infrastructure.db.outbox import SqlAlchemyOutbox
from ledger.infrastructure.db.outbox_store import SqlAlchemyOutboxStore
from ledger.infrastructure.db.repositories import (
    SqlAlchemyLedgerQueries,
    SqlAlchemyLedgerRepository,
    SqlAlchemyOrderProjectionRepository,
)


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._orders: SqlAlchemyOrderProjectionRepository | None = None
        self._ledger: SqlAlchemyLedgerRepository | None = None
        self._queries: SqlAlchemyLedgerQueries | None = None
        self._outbox: SqlAlchemyOutbox | None = None
        self._outbox_store: SqlAlchemyOutboxStore | None = None
        self._inbox: SqlAlchemyInboxStore | None = None

    @property
    def orders(self) -> SqlAlchemyOrderProjectionRepository:
        assert self._orders is not None, "use inside 'async with'"
        return self._orders

    @property
    def ledger(self) -> SqlAlchemyLedgerRepository:
        assert self._ledger is not None, "use inside 'async with'"
        return self._ledger

    @property
    def queries(self) -> SqlAlchemyLedgerQueries:
        assert self._queries is not None, "use inside 'async with'"
        return self._queries

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
        self._orders = SqlAlchemyOrderProjectionRepository(self._session)
        self._ledger = SqlAlchemyLedgerRepository(self._session)
        self._queries = SqlAlchemyLedgerQueries(self._session)
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
