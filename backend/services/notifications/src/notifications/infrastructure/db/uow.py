from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from notifications.infrastructure.db.inbox import SqlAlchemyInboxStore
from notifications.infrastructure.db.repositories import (
    SqlAlchemyNotificationRepository,
    SqlAlchemyOrderProjectionRepository,
)


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._notifications: SqlAlchemyNotificationRepository | None = None
        self._orders: SqlAlchemyOrderProjectionRepository | None = None
        self._inbox: SqlAlchemyInboxStore | None = None

    @property
    def notifications(self) -> SqlAlchemyNotificationRepository:
        assert self._notifications is not None, "use inside 'async with'"
        return self._notifications

    @property
    def orders(self) -> SqlAlchemyOrderProjectionRepository:
        assert self._orders is not None, "use inside 'async with'"
        return self._orders

    @property
    def inbox(self) -> SqlAlchemyInboxStore:
        assert self._inbox is not None, "use inside 'async with'"
        return self._inbox

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self._notifications = SqlAlchemyNotificationRepository(self._session)
        self._orders = SqlAlchemyOrderProjectionRepository(self._session)
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
