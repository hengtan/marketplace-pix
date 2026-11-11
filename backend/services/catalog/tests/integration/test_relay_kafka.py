from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaConsumer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from marketplace_common.events import REGISTRY
from marketplace_common.messaging import KafkaPublisher, OutboxRelay
from marketplace_common.security import Principal, scopes_for_roles
from sqlalchemy import text, update

from catalog.application.commands import ManageProducts
from catalog.config import load_settings
from catalog.infrastructure.db.models import OutboxEventModel
from catalog.infrastructure.db.uow import SqlAlchemyUnitOfWork
from catalog.seed_data import merchant_id, product_id

BOOTSTRAP = load_settings().kafka_bootstrap_servers
FONE = product_id("fone-bluetooth-nova")


@pytest.fixture
async def topic():
    name = f"test.catalog.events.{uuid4().hex[:8]}"
    admin = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP)
    await admin.start()
    await admin.create_topics([NewTopic(name, num_partitions=3, replication_factor=1)])
    yield name
    await admin.delete_topics([name])
    await admin.close()


@pytest.fixture
async def publisher():
    publisher = KafkaPublisher(BOOTSTRAP)
    await publisher.start()
    yield publisher
    await publisher.stop()


async def consume(topic: str, expected: int, timeout: float = 10.0) -> list:
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=BOOTSTRAP,
        group_id=f"test-{uuid4().hex[:8]}",
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )
    await consumer.start()
    received = []
    try:
        async with asyncio.timeout(timeout):
            while len(received) < expected:
                received.append(await consumer.getone())
    except TimeoutError:
        pass
    finally:
        await consumer.stop()
    return received


async def test_relay_publishes_the_catalog_events_keyed_by_product(
    seeded, engine, publisher, topic
) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("truncate outbox_events"))
    owner = Principal(
        uuid4(),
        frozenset({"merchant"}),
        scopes_for_roles(frozenset({"merchant"})),
        merchant_id("aurora-tech"),
    )
    manage = ManageProducts(lambda: SqlAlchemyUnitOfWork(seeded))
    await manage.update(owner, FONE, {"price_cents": 29990, "name": "Fone Nova ANC 2"})
    await manage.deactivate(owner, FONE)
    async with seeded() as session:
        await session.execute(update(OutboxEventModel).values(topic=topic))
        await session.commit()

    relay = OutboxRelay(lambda: SqlAlchemyUnitOfWork(seeded), publisher)
    assert await relay.run_once() == 3

    records = await consume(topic, 3)
    assert len(records) == 3
    seen = set()
    for record in records:
        headers = {k: v.decode() for k, v in record.headers}
        payload = json.loads(record.value)
        assert record.key.decode() == str(FONE) == payload["product_id"]
        assert headers["event_type"] in {
            "ProductPriceChanged",
            "ProductUpdated",
            "ProductDeactivated",
        }
        assert headers["schema_version"] == "1" == str(payload["schema_version"])
        REGISTRY.parse(headers["event_type"], payload)
        seen.add(headers["event_type"])
    assert seen == {"ProductPriceChanged", "ProductUpdated", "ProductDeactivated"}
    assert await relay.run_once() == 0
