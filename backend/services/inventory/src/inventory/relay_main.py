from __future__ import annotations

import asyncio
import logging
import signal

from inventory.application.outbox_relay import OutboxRelay
from inventory.config import load_settings
from inventory.infrastructure.db.session import build_engine, build_session_factory
from inventory.infrastructure.db.uow import SqlAlchemyUnitOfWork
from inventory.infrastructure.messaging.kafka_publisher import KafkaPublisher


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings()
    engine = build_engine(settings.database_url)
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
