from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from payments.config import load_settings
from payments.infrastructure.db.session import build_engine, build_session_factory
from payments.infrastructure.db.uow import SqlAlchemyUnitOfWork
from payments.infrastructure.psp.simulated import SimulatedPsp
from payments.interface.api import ReadyCheck, create_app


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
    psp = SimulatedPsp(factory)
    app.state.uow_factory = lambda: SqlAlchemyUnitOfWork(factory)
    app.state.psp = psp
    app.state.webhook_secret = settings.psp_webhook_secret
    app.state.ready_check = _db_check(engine)
    if settings.enable_dev_psp:
        app.state.dev_psp = psp
    yield
    await engine.dispose()


app = create_app(lifespan=lifespan)
