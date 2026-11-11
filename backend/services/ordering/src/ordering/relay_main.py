from __future__ import annotations

import asyncio
import logging
import signal

from marketplace_common.messaging import KafkaPublisher, OutboxRelay
from marketplace_common.observability import instrument_sqlalchemy, setup_worker_observability

from ordering.config import load_settings
from ordering.infrastructure.db.session import build_engine, build_session_factory
from ordering.infrastructure.db.uow import SqlAlchemyUnitOfWork


async def main() -> None:
    setup_worker_observability("ordering-relay")
    settings = load_settings()
    engine = build_engine(settings.database_url)
    instrument_sqlalchemy(engine)
    session_factory = build_session_factory(engine)
    publisher = KafkaPublisher(settings.kafka_bootstrap_servers)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await publisher.start()
    try:
        relay = OutboxRelay(lambda: SqlAlchemyUnitOfWork(session_factory), publisher)
        logging.getLogger(__name__).info("outbox relay started")
        await relay.run_forever(stop)
    finally:
        await publisher.stop()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
