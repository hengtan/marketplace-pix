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

from payments.application.expire_payments import ExpirePayments
from payments.application.handle_order_event import HandleOrderEvent
from payments.config import load_settings
from payments.infrastructure.db.session import build_engine, build_session_factory
from payments.infrastructure.db.uow import SqlAlchemyUnitOfWork
from payments.infrastructure.psp.simulated import SimulatedPsp

ORDERS_TOPIC = "orders.events"
CONSUMER_GROUP = "payments"


async def main() -> None:
    setup_worker_observability("payments-worker")
    settings = load_settings()
    engine = build_engine(settings.database_url)
    instrument_sqlalchemy(engine)
    factory = build_session_factory(engine)
    uow_factory = lambda: SqlAlchemyUnitOfWork(factory)  # noqa: E731

    handler = HandleOrderEvent(
        uow_factory, SimulatedPsp(factory), ttl=timedelta(minutes=settings.pix_ttl_minutes)
    )
    consumer = KafkaEventConsumer(
        settings.kafka_bootstrap_servers, ORDERS_TOPIC, CONSUMER_GROUP, handler
    )
    expirer = ExpirePayments(uow_factory)

    policy = RetentionPolicy.from_env()
    cleanup = CleanupJob(engine, [outbox_target(policy), inbox_target(policy)], policy)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await consumer.start()
    try:
        logging.getLogger(__name__).info("payments worker started")
        await asyncio.gather(
            consumer.run(stop), expirer.run_forever(stop), cleanup.run_forever(stop)
        )
    finally:
        await consumer.stop()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
