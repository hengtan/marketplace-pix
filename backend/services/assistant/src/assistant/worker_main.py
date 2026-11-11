import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable

from marketplace_common.messaging import KafkaEventConsumer
from marketplace_common.observability import setup_worker_observability

from assistant.application.catalog_events import CATALOG_TOPIC, CatalogEventHandler
from assistant.config import load_settings
from assistant.infrastructure.db.session import build_engine
from assistant.wiring import build_container

CONSUMER_GROUP = "assistant"
PURGE_INTERVAL_SECONDS = 300


async def purge_loop(purge: Callable[[], Awaitable[int]], stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), PURGE_INTERVAL_SECONDS)
        except TimeoutError:
            await purge()


async def main() -> None:
    setup_worker_observability("assistant-worker")
    settings = load_settings()
    engine = build_engine(settings.database_url)
    container = build_container(settings, engine)
    handler = CatalogEventHandler(container.ingest, container.cache)
    consumer = KafkaEventConsumer(
        settings.kafka_bootstrap_servers, CATALOG_TOPIC, CONSUMER_GROUP, handler
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await consumer.start()
    try:
        logging.getLogger(__name__).info("assistant worker started")
        await asyncio.gather(consumer.run(stop), purge_loop(container.cache.purge_expired, stop))
    finally:
        await consumer.stop()
        await container.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
