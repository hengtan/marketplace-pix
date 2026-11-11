from __future__ import annotations

import asyncio
import logging
import signal

from marketplace_common.maintenance import (
    CleanupJob,
    RetentionPolicy,
    idempotency_target,
    inbox_target,
    outbox_target,
)
from marketplace_common.messaging import KafkaEventConsumer
from marketplace_common.observability import instrument_sqlalchemy, setup_worker_observability

from ordering.application.handle_saga_event import HandleSagaEvent
from ordering.config import load_settings
from ordering.infrastructure.db.session import build_engine, build_session_factory
from ordering.infrastructure.db.uow import SqlAlchemyUnitOfWork

PAYMENTS_TOPIC = "payments.events"
INVENTORY_TOPIC = "inventory.events"


async def main() -> None:
    setup_worker_observability("ordering-worker")
    settings = load_settings()
    engine = build_engine(settings.database_url)
    instrument_sqlalchemy(engine)
    factory = build_session_factory(engine)

    handler = HandleSagaEvent(lambda: SqlAlchemyUnitOfWork(factory))
    consumers = [
        KafkaEventConsumer(settings.kafka_bootstrap_servers, PAYMENTS_TOPIC, "ordering", handler),
        KafkaEventConsumer(
            settings.kafka_bootstrap_servers, INVENTORY_TOPIC, "ordering-inventory", handler
        ),
    ]

    policy = RetentionPolicy.from_env()
    cleanup = CleanupJob(
        engine,
        [outbox_target(policy), inbox_target(policy), idempotency_target(policy)],
        policy,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    for consumer in consumers:
        await consumer.start()
    try:
        logging.getLogger(__name__).info("ordering worker started")
        await asyncio.gather(
            *(consumer.run(stop) for consumer in consumers),
            cleanup.run_forever(stop),
        )
    finally:
        for consumer in consumers:
            await consumer.stop()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
