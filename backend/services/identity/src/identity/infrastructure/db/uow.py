from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from identity.infrastructure.db.repositories import (
    SqlAlchemyRefreshTokenRepository,
    SqlAlchemyUserRepository,
)


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._users: SqlAlchemyUserRepository | None = None
        self._refresh_tokens: SqlAlchemyRefreshTokenRepository | None = None

    @property
    def users(self) -> SqlAlchemyUserRepository:
        assert self._users is not None, "use inside 'async with'"
        return self._users

    @property
    def refresh_tokens(self) -> SqlAlchemyRefreshTokenRepository:
        assert self._refresh_tokens is not None, "use inside 'async with'"
        return self._refresh_tokens

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self._users = SqlAlchemyUserRepository(self._session)
        self._refresh_tokens = SqlAlchemyRefreshTokenRepository(self._session)
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
