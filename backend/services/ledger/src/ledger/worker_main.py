from __future__ import annotations

import asyncio
import logging
import signal

from marketplace_common.maintenance import (
    CleanupJob,
    RetentionPolicy,
    inbox_target,
    outbox_target,
)
from marketplace_common.messaging import KafkaEventConsumer
from marketplace_common.observability import instrument_sqlalchemy, setup_worker_observability

from ledger.application.handle_order_event import HandleOrderEvent
from ledger.application.handle_payment_event import HandlePaymentEvent
from ledger.config import load_settings
from ledger.infrastructure.db.session import build_engine, build_session_factory
from ledger.infrastructure.db.uow import SqlAlchemyUnitOfWork

ORDERS_TOPIC = "orders.events"
ORDERS_GROUP = "ledger-orders"
PAYMENTS_TOPIC = "payments.events"
PAYMENTS_GROUP = "ledger-payments"


async def main() -> None:
    setup_worker_observability("ledger-worker")
    settings = load_settings()
    engine = build_engine(settings.database_url)
    instrument_sqlalchemy(engine)
    factory = build_session_factory(engine)
    uow_factory = lambda: SqlAlchemyUnitOfWork(factory)  # noqa: E731

    orders = KafkaEventConsumer(
        settings.kafka_bootstrap_servers, ORDERS_TOPIC, ORDERS_GROUP, HandleOrderEvent(uow_factory)
    )
    payments = KafkaEventConsumer(
        settings.kafka_bootstrap_servers,
        PAYMENTS_TOPIC,
        PAYMENTS_GROUP,
        HandlePaymentEvent(uow_factory, fee_bps=settings.platform_fee_bps),
    )

    policy = RetentionPolicy.from_env()
    cleanup = CleanupJob(engine, [outbox_target(policy), inbox_target(policy)], policy)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    await orders.start()
    await payments.start()
    try:
        logging.getLogger(__name__).info("ledger worker started")
        await asyncio.gather(orders.run(stop), payments.run(stop), cleanup.run_forever(stop))
    finally:
        await orders.stop()
        await payments.stop()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
