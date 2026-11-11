from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from marketplace_common.observability import install_api_observability, instrument_sqlalchemy
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from assistant.config import load_settings
from assistant.infrastructure.db.session import build_engine
from assistant.interface.api import ReadyCheck, create_app
from assistant.wiring import build_container


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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = load_settings()
    engine = build_engine(settings.database_url)
    instrument_sqlalchemy(engine)
    container = build_container(settings, engine)
    app.state.container = container
    app.state.ready_check = _db_check(engine)
    yield
    await container.aclose()
    await engine.dispose()


app = create_app(lifespan=lifespan)
install_api_observability(app, "assistant-api")
