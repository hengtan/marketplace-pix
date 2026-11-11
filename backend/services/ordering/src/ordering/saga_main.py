from __future__ import annotations

import asyncio
import sys
from datetime import timedelta

from marketplace_common.observability import setup_logging

from ordering.application.saga_timeout import SagaTimeoutManager
from ordering.config import load_settings
from ordering.infrastructure.db.session import build_engine, build_session_factory
from ordering.infrastructure.db.uow import SqlAlchemyUnitOfWork


async def main() -> None:
    setup_logging("ordering-saga")
    settings = load_settings()
    engine = build_engine(settings.database_url)
    try:
        manager = SagaTimeoutManager(
            lambda: SqlAlchemyUnitOfWork(build_session_factory(engine)),
            timedelta(seconds=settings.saga_timeout_seconds),
            settings.saga_sweep_batch_size,
        )
        cancelled = await manager.run_once()
        print(f"saga sweep: {cancelled} orders cancelled")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    if "--once" not in sys.argv[1:]:
        sys.exit("usage: python -m ordering.saga_main --once")
    asyncio.run(main())
