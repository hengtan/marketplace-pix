from __future__ import annotations

import asyncio
import logging
import signal

from ordering.application.handle_saga_event import HandleSagaEvent
from ordering.config import load_settings
from ordering.infrastructure.db.session import build_engine, build_session_factory
from ordering.infrastructure.db.uow import SqlAlchemyUnitOfWork
from ordering.infrastructure.messaging.kafka_consumer import KafkaEventConsumer

PAYMENTS_TOPIC = "payments.events"
INVENTORY_TOPIC = "inventory.events"


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)

    handler = HandleSagaEvent(lambda: SqlAlchemyUnitOfWork(factory))
    consumers = [
        KafkaEventConsumer(settings.kafka_bootstrap_servers, PAYMENTS_TOPIC, "ordering", handler),
        KafkaEventConsumer(
            settings.kafka_bootstrap_servers, INVENTORY_TOPIC, "ordering-inventory", handler
        ),
    ]

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    for consumer in consumers:
        await consumer.start()
    try:
        logging.getLogger(__name__).info("ordering worker started")
        await asyncio.gather(*(consumer.run(stop) for consumer in consumers))
    finally:
        for consumer in consumers:
            await consumer.stop()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
