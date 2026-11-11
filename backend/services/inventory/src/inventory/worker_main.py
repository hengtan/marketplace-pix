from __future__ import annotations

import asyncio
import logging
import signal
from datetime import timedelta

from marketplace_common.maintenance import (
    CleanupJob,
    RetentionPolicy,
    inbox_target,
    outbox_target,
)
from marketplace_common.messaging import KafkaEventConsumer
from marketplace_common.observability import instrument_sqlalchemy, setup_worker_observability

from inventory.application.event_handlers import (
    CATALOG_CONSUMER,
    ORDERS_CONSUMER,
    PAYMENTS_CONSUMER,
    HandleCatalogEvent,
    HandleOrderEvent,
    HandlePaymentEvent,
)
from inventory.application.expire_reservations import ExpireReservations
from inventory.config import load_settings
from inventory.infrastructure.db.session import build_engine, build_session_factory
from inventory.infrastructure.db.uow import SqlAlchemyUnitOfWork

ORDERS_TOPIC = "orders.events"
PAYMENTS_TOPIC = "payments.events"
CATALOG_TOPIC = "catalog.events"


async def main() -> None:
    setup_worker_observability("inventory-worker")
    settings = load_settings()
    engine = build_engine(settings.database_url)
    instrument_sqlalchemy(engine)
    factory = build_session_factory(engine)

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(factory)

    ttl = timedelta(minutes=settings.reservation_ttl_minutes)
    orders_consumer = KafkaEventConsumer(
        settings.kafka_bootstrap_servers,
        ORDERS_TOPIC,
        ORDERS_CONSUMER,
        HandleOrderEvent(uow_factory, ttl),
    )
    payments_consumer = KafkaEventConsumer(
        settings.kafka_bootstrap_servers,
        PAYMENTS_TOPIC,
        PAYMENTS_CONSUMER,
        HandlePaymentEvent(uow_factory),
    )
    catalog_consumer = KafkaEventConsumer(
        settings.kafka_bootstrap_servers,
        CATALOG_TOPIC,
        CATALOG_CONSUMER,
        HandleCatalogEvent(uow_factory),
    )
    expirer = ExpireReservations(uow_factory)

    policy = RetentionPolicy.from_env()
    cleanup = CleanupJob(engine, [outbox_target(policy), inbox_target(policy)], policy)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await orders_consumer.start()
    await payments_consumer.start()
    await catalog_consumer.start()
    try:
        logging.getLogger(__name__).info("inventory worker started")
        await asyncio.gather(
            orders_consumer.run(stop),
            payments_consumer.run(stop),
            catalog_consumer.run(stop),
            expirer.run_forever(stop, interval=settings.expiry_interval_seconds),
            cleanup.run_forever(stop),
        )
    finally:
        await orders_consumer.stop()
        await payments_consumer.stop()
        await catalog_consumer.stop()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
