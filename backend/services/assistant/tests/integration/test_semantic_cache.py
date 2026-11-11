import asyncio
import contextlib
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
from aiokafka import AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from marketplace_common.messaging import IncomingEvent, KafkaEventConsumer

from assistant.application.catalog_events import CatalogEventHandler
from assistant.application.ports import Prompt
from assistant.application.semantic_cache import CacheConfig
from assistant.config import Settings
from assistant.infrastructure.fixtures import FixtureInventoryGateway
from assistant.infrastructure.llm.mock import MockLlm
from assistant.interface.api import create_app
from assistant.wiring import Container, build_container
from tests.helpers import pid


class CountingLlm(MockLlm):
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, prompt: Prompt) -> str:
        self.calls += 1
        return await super().generate(prompt)

    async def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        self.calls += 1
        async for token in super().stream(prompt):
            yield token


def event(kind: str, slug: str) -> IncomingEvent:
    product = pid(slug)
    return IncomingEvent(uuid4(), kind, str(product), {"product_id": str(product)})


@pytest.fixture
async def cached(settings: Settings, engine, catalog, snapshot_products, orders):  # type: ignore[no-untyped-def]
    llm = CountingLlm()
    built = build_container(
        Settings(assistant_db=settings.assistant_db, cache_enabled=True),  # type: ignore[call-arg]
        engine,
        catalog=catalog,
        inventory=FixtureInventoryGateway(snapshot_products),
        orders=orders,
        llm=llm,
        token_delay_seconds=0.0,
    )
    await built.ingest.execute()
    yield built, llm
    await built.aclose()


async def ask(container: Container, message: str, session=None):  # type: ignore[no-untyped-def]
    return await container.chat.chat(session, message)


async def test_repeated_and_paraphrased_questions_hit_the_cache(cached) -> None:  # type: ignore[no-untyped-def]
    container, llm = cached
    first = await ask(container, "quero um fone com cancelamento de ruído")
    assert not first.cached and llm.calls == 1
    again = await ask(container, "quero um fone com cancelamento de ruído")
    paraphrase = await ask(container, "Quero um fone, com cancelamento de ruido!")
    assert again.cached and paraphrase.cached and llm.calls == 1
    assert again.answer == first.answer and again.citations == first.citations
    assert [t.name for t in again.tool_calls] == ["search_products"]
    assert [p.slug for p in again.retrieved] == [p.slug for p in first.retrieved]

    stats = container.cache.stats
    assert (stats.hits, stats.misses) == (2, 1) and stats.hit_rate == pytest.approx(2 / 3, abs=1e-3)
    assert stats.tokens_saved > 0 and stats.cost_saved_usd > 0
    summary = await container.cache.summary()
    assert summary.entries == 1 and summary.hits == 2 and summary.tokens_saved > 0


async def test_different_filters_and_negations_do_not_share_an_entry(cached) -> None:  # type: ignore[no-untyped-def]
    container, llm = cached
    cheap = await ask(container, "algo para treinar até R$ 60")
    wide = await ask(container, "algo para treinar até R$ 200")
    assert not wide.cached and cheap.answer != wide.answer
    plain = await ask(container, "quero um fone com cancelamento de ruído")
    negated = await ask(container, "quero um fone sem cancelamento de ruído")
    assert not plain.cached and not negated.cached


async def test_live_data_and_history_dependent_questions_are_never_cached(cached) -> None:  # type: ignore[no-untyped-def]
    container, llm = cached
    first = await ask(container, "tem estoque do relógio GPS?")
    second = await ask(container, "tem estoque do relógio GPS?")
    assert not first.cached and not second.cached
    session = (await ask(container, "luminária para sala")).session_id
    follow = await ask(container, "qual o mais barato deles?", session)
    other = await ask(container, "qual o mais barato deles?")
    assert not follow.cached and not other.cached
    assert follow.answer != other.answer


async def test_entries_expire_by_ttl(settings, engine, catalog, snapshot_products, orders) -> None:  # type: ignore[no-untyped-def]
    short = Settings(assistant_db=settings.assistant_db, cache_enabled=True, cache_ttl_seconds=1)  # type: ignore[call-arg]
    built = build_container(
        short,
        engine,
        catalog=catalog,
        inventory=FixtureInventoryGateway(snapshot_products),
        orders=orders,
        token_delay_seconds=0.0,
    )
    try:
        await built.ingest.execute()
        await ask(built, "luminária para sala")
        assert (await ask(built, "luminária para sala")).cached
        await asyncio.sleep(1.3)
        assert not (await ask(built, "luminária para sala")).cached
        assert await built.cache.purge_expired() >= 0
    finally:
        await built.aclose()


async def test_price_change_event_invalidates_cited_answers(cached, catalog) -> None:  # type: ignore[no-untyped-def]
    container, llm = cached
    handler = CatalogEventHandler(container.ingest, container.cache)
    before = await ask(container, "quero um fone com cancelamento de ruído")
    assert "R$ 349,90" in before.answer
    assert (await ask(container, "quero um fone com cancelamento de ruído")).cached

    catalog.products = [
        p if p.slug != "fone-bluetooth-nova" else _repriced(p, 29990) for p in catalog.products
    ]
    outcome = await handler.handle(event("ProductPriceChanged", "fone-bluetooth-nova"))
    assert outcome["cache_invalidated"] == 1 and outcome["reindexed"] >= 1

    after = await ask(container, "quero um fone com cancelamento de ruído")
    assert not after.cached and "R$ 299,90" in after.answer and "R$ 349,90" not in after.answer


async def test_deactivated_product_leaves_the_index_and_the_cited_answers(cached, catalog) -> None:  # type: ignore[no-untyped-def]
    container, llm = cached
    handler = CatalogEventHandler(container.ingest, container.cache)
    before = await ask(container, "quero um fone com cancelamento de ruído")
    assert "Fone Bluetooth Nova" in before.answer

    catalog.products = [p for p in catalog.products if p.slug != "fone-bluetooth-nova"]
    outcome = await handler.handle(event("ProductDeactivated", "fone-bluetooth-nova"))
    assert outcome["cache_invalidated"] == 1
    assert outcome["reindexed"] == 0

    after = await ask(container, "quero um fone com cancelamento de ruído")
    assert not after.cached and "Fone Bluetooth Nova" not in after.answer


def _repriced(product, cents):  # type: ignore[no-untyped-def]
    from dataclasses import replace

    return replace(product, price_cents=cents)


async def test_unrelated_events_keep_entries_but_created_flushes_volatile_ones(cached) -> None:  # type: ignore[no-untyped-def]
    container, llm = cached
    handler = CatalogEventHandler(container.ingest, container.cache)
    await ask(container, "luminária para sala")
    await ask(container, "algo para treinar até R$ 100")
    assert (await container.cache.summary()).entries == 2

    await handler.handle(event("ProductDeleted", "mochila-trilha-30l"))
    assert (await container.cache.summary()).entries == 2
    await handler.handle(event("ProductDeactivated", "mochila-trilha-30l"))
    assert (await container.cache.summary()).entries == 2
    assert (await handler.handle(event("OrderCreated", "x")))["ignored"]

    await handler.handle(event("ProductCreated", "mochila-trilha-30l"))
    assert (await container.cache.summary()).entries == 1
    await handler.handle(event("ProductUpdated", "luminaria-arco-dourado"))
    assert (await container.cache.summary()).entries == 0


async def test_cache_can_be_disabled(settings, engine, catalog, snapshot_products, orders) -> None:  # type: ignore[no-untyped-def]
    off = Settings(assistant_db=settings.assistant_db, cache_enabled=False)  # type: ignore[call-arg]
    built = build_container(
        off,
        engine,
        catalog=catalog,
        inventory=FixtureInventoryGateway(snapshot_products),
        orders=orders,
        token_delay_seconds=0.0,
    )
    try:
        await built.ingest.execute()
        await ask(built, "luminária para sala")
        assert not (await ask(built, "luminária para sala")).cached
        assert CacheConfig(enabled=False).enabled is False
    finally:
        await built.aclose()


async def test_kafka_catalog_event_invalidates_the_cache(cached, settings) -> None:  # type: ignore[no-untyped-def]
    container, llm = cached
    await ask(container, "luminária para sala")
    assert (await container.cache.summary()).entries == 1

    topic = f"catalog.events.test.{uuid4().hex[:8]}"
    admin = AIOKafkaAdminClient(bootstrap_servers=settings.kafka_bootstrap_servers)
    producer = AIOKafkaProducer(bootstrap_servers=settings.kafka_bootstrap_servers)
    try:
        await admin.start()
        await admin.create_topics([NewTopic(topic, 1, 1)])
        await producer.start()
    except Exception:
        with contextlib.suppress(Exception):
            await admin.close()
        pytest.skip("kafka is not reachable")
    handler = CatalogEventHandler(container.ingest, container.cache)
    consumer = KafkaEventConsumer(
        settings.kafka_bootstrap_servers, topic, f"assistant-test-{uuid4().hex[:6]}", handler
    )
    stop = asyncio.Event()
    await consumer.start()
    runner = asyncio.create_task(consumer.run(stop))
    try:
        product = pid("luminaria-arco-dourado")
        await producer.send_and_wait(
            topic,
            key=str(product).encode(),
            value=b'{"product_id": "%s"}' % str(product).encode(),
            headers=[
                ("event_id", str(uuid4()).encode()),
                ("event_type", b"ProductUpdated"),
            ],
        )
        for _ in range(100):
            if (await container.cache.summary()).entries == 0:
                break
            await asyncio.sleep(0.2)
        assert (await container.cache.summary()).entries == 0
    finally:
        stop.set()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(runner, 5)
        await consumer.stop()
        await producer.stop()
        with contextlib.suppress(Exception):
            await admin.delete_topics([topic])
        await admin.close()


async def test_cache_stats_endpoint_and_cached_flag(cached) -> None:  # type: ignore[no-untyped-def]
    container, _ = cached
    app = create_app(container=container)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        body = {"message": "luminária para sala"}
        first = (await client.post("/chat", json=body)).json()
        second = (await client.post("/chat", json=body)).json()
        assert first["cached"] is False and second["cached"] is True
        stats = (await client.get("/cache/stats")).json()
    assert stats["enabled"] and stats["entries"] == 1
    assert (stats["hits"], stats["misses"], stats["hit_rate"]) == (1, 1, 0.5)
    assert stats["tokens_saved"] > 0 and stats["persisted_hits"] == 1
