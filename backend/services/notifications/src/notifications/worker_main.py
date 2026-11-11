from __future__ import annotations

import asyncio
import logging
import signal

from notifications.application.handle_event import HandleEvent
from notifications.config import load_settings
from notifications.infrastructure.db.session import build_engine, build_session_factory
from notifications.infrastructure.db.uow import SqlAlchemyUnitOfWork
from notifications.infrastructure.messaging.kafka_consumer import KafkaEventConsumer
from notifications.worker.queue import CeleryNotificationQueue

TOPICS = ("orders.events", "payments.events")
CONSUMER_GROUP = "notifications"


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)

    handler = HandleEvent(
        lambda: SqlAlchemyUnitOfWork(factory),
        CeleryNotificationQueue(),
        base_url=settings.frontend_base_url,
    )
    consumer = KafkaEventConsumer(settings.kafka_bootstrap_servers, TOPICS, CONSUMER_GROUP, handler)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await consumer.start()
    try:
        logging.getLogger(__name__).info("notifications consumer started")
        await consumer.run(stop)
    finally:
        await consumer.stop()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
