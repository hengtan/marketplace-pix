from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from marketplace_common.observability import install_api_observability, instrument_sqlalchemy
from marketplace_common.security import PrincipalResolver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from catalog.application.commands import ManageProducts
from catalog.config import load_settings
from catalog.infrastructure.db.repository import build_reader_factory
from catalog.infrastructure.db.session import build_engine, build_session_factory
from catalog.infrastructure.db.uow import SqlAlchemyUnitOfWork
from catalog.interface.api import ReadyCheck, create_app


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
    instrument_sqlalchemy(engine)
    factory = build_session_factory(engine)
    app.state.reader_factory = build_reader_factory(factory)
    app.state.manage_products = ManageProducts(lambda: SqlAlchemyUnitOfWork(factory))
    app.state.principal_resolver = PrincipalResolver(settings.internal_auth_secret)
    app.state.cache_max_age = settings.cache_max_age_seconds
    app.state.ready_check = _db_check(engine)
    yield
    await engine.dispose()


app = create_app(lifespan=lifespan)
install_api_observability(app, "catalog-api")
