from __future__ import annotations

import asyncio
import logging
import signal

from ordering.application.handle_payment_event import HandlePaymentEvent
from ordering.config import load_settings
from ordering.infrastructure.db.session import build_engine, build_session_factory
from ordering.infrastructure.db.uow import SqlAlchemyUnitOfWork
from ordering.infrastructure.messaging.kafka_consumer import KafkaEventConsumer

PAYMENTS_TOPIC = "payments.events"
CONSUMER_GROUP = "ordering"


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)

    handler = HandlePaymentEvent(lambda: SqlAlchemyUnitOfWork(factory))
    consumer = KafkaEventConsumer(
        settings.kafka_bootstrap_servers, PAYMENTS_TOPIC, CONSUMER_GROUP, handler
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await consumer.start()
    try:
        logging.getLogger(__name__).info("ordering worker started")
        await consumer.run(stop)
    finally:
        await consumer.stop()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
