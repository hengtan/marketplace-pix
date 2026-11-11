from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool


def build_engine(url: str, *, pooled: bool = True) -> AsyncEngine:
    if pooled:
        return create_async_engine(url, pool_pre_ping=True)
    return create_async_engine(url, poolclass=NullPool)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
