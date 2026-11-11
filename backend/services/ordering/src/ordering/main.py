from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from marketplace_common.observability import install_api_observability, instrument_sqlalchemy
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ordering.config import load_settings
from ordering.infrastructure.catalog.http_catalog import HttpCatalogGateway
from ordering.infrastructure.db.session import build_engine, build_session_factory
from ordering.infrastructure.db.uow import SqlAlchemyUnitOfWork
from ordering.interface.api import ReadyCheck, create_app


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
    catalog = HttpCatalogGateway(settings.catalog_url)
    app.state.uow_factory = lambda: SqlAlchemyUnitOfWork(factory)
    app.state.catalog = catalog
    app.state.ready_check = _db_check(engine)
    yield
    await catalog.aclose()
    await engine.dispose()


app = create_app(lifespan=lifespan)
install_api_observability(app, "ordering-api")
