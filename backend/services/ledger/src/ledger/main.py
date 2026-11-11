from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ledger.config import load_settings
from ledger.infrastructure.db.session import build_engine, build_session_factory
from ledger.infrastructure.db.uow import SqlAlchemyUnitOfWork
from ledger.interface.api import ReadyCheck, create_app


def _db_check(engine: AsyncEngine) -> ReadyCheck:
    async def check() -> bool:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("select 1"))
        except Exception:
            return False
        return True

    return check


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = load_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    app.state.uow_factory = lambda: SqlAlchemyUnitOfWork(factory)
    app.state.ready_check = _db_check(engine)
    yield
    await engine.dispose()


app = create_app(lifespan=lifespan)
