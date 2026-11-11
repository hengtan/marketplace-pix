from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from catalog.infrastructure.db.outbox import SqlAlchemyOutbox
from catalog.infrastructure.db.outbox_store import SqlAlchemyOutboxStore
from catalog.infrastructure.db.writer import SqlAlchemyProductWriter


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._products: SqlAlchemyProductWriter | None = None
        self._outbox: SqlAlchemyOutbox | None = None
        self._outbox_store: SqlAlchemyOutboxStore | None = None

    @property
    def products(self) -> SqlAlchemyProductWriter:
        assert self._products is not None, "use inside 'async with'"
        return self._products

    @property
    def outbox(self) -> SqlAlchemyOutbox:
        assert self._outbox is not None, "use inside 'async with'"
        return self._outbox

    @property
    def outbox_store(self) -> SqlAlchemyOutboxStore:
        assert self._outbox_store is not None, "use inside 'async with'"
        return self._outbox_store

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self._products = SqlAlchemyProductWriter(self._session)
        self._outbox = SqlAlchemyOutbox(self._session)
        self._outbox_store = SqlAlchemyOutboxStore(self._session)
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
