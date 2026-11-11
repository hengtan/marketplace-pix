import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest
from prometheus_client import REGISTRY

from assistant.application.chat import StreamTimeouts
from assistant.application.ports import Prompt
from assistant.config import Settings
from assistant.domain.errors import UpstreamUnavailable
from assistant.infrastructure.fixtures import FixtureInventoryGateway
from assistant.infrastructure.llm.mock import MockLlm
from assistant.interface.api import create_app
from assistant.wiring import Container, build_container


def sample(name: str, labels: dict[str, str] | None = None) -> float:
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


class FailingLlm(MockLlm):
    name = "failing"

    async def generate(self, prompt: Prompt) -> str:
        raise UpstreamUnavailable("down")

    async def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        raise UpstreamUnavailable("down")
        yield ""


class HangingLlm(MockLlm):
    name = "hanging"

    async def generate(self, prompt: Prompt) -> str:
        await asyncio.sleep(30)
        return "nunca"

    async def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        await asyncio.sleep(30)
        yield "nunca"


class DiesMidStream(MockLlm):
    name = "dies"

    async def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        yield "Encontrei "
        yield "algumas "
        raise UpstreamUnavailable("connection reset")


class StallsAfterFirstToken(MockLlm):
    name = "stalls"

    async def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        yield "Olá "
        await asyncio.sleep(30)
        yield "nunca"


class SlowTokens(MockLlm):
    name = "slow-tokens"

    def __init__(self) -> None:
        self.closed = asyncio.Event()
        self.produced = 0

    async def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        try:
            for index in range(200):
                self.produced += 1
                yield f"palavra{index} "
                await asyncio.sleep(0.02)
        finally:
            self.closed.set()


def build(settings, engine, catalog, products, orders, llm, **overrides) -> Container:  # type: ignore[no-untyped-def]
    config = Settings(  # type: ignore[call-arg]
        assistant_db=settings.assistant_db, cache_enabled=False, **overrides
    )
    return build_container(
        config,
        engine,
        catalog=catalog,
        inventory=FixtureInventoryGateway(products),
        orders=orders,
        llm=llm,
        token_delay_seconds=0.0,
    )


async def test_model_failure_returns_the_search_results_with_a_warning(
    settings,
    engine,
    catalog,
    snapshot_products,
    orders,  # type: ignore[no-untyped-def]
) -> None:
    container = build(settings, engine, catalog, snapshot_products, orders, FailingLlm())
    await container.ingest.execute()
    before = sample("assistant_fallback_total", {"reason": "llm_error"})
    app = create_app(container=container)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/chat", json={"message": "quero um fone com cancelamento"})
        assert response.status_code == 200
        body = response.json()
        assert body["degraded"] is True and "indisponível" in body["warning"]
        assert "Fone Bluetooth Nova ANC por R$ 349,90" in body["answer"]
        assert body["citations"][0]["slug"] == "fone-bluetooth-nova"
        assert [t["name"] for t in body["tool_calls"]] == ["search_products"]

        stream = await client.post("/chat/stream", json={"message": "luminária para sala"})
        kinds = [line[7:] for line in stream.text.splitlines() if line.startswith("event: ")]
        assert kinds == ["tool_call", "warning", "done"]
        done = json.loads(stream.text.split("event: done\ndata: ")[1].split("\n")[0])
        assert done["degraded"] and "Luminária Arco Dourado" in done["answer"]

        session = (await client.get(f"/sessions/{done['session_id']}")).json()
        assert session["messages"][-1]["content"] == done["answer"]
    assert sample("assistant_fallback_total", {"reason": "llm_error"}) == before + 2
    await container.aclose()


async def test_stalled_model_hits_the_first_token_timeout_and_degrades_fast(
    settings,
    engine,
    catalog,
    snapshot_products,
    orders,  # type: ignore[no-untyped-def]
) -> None:
    container = build(settings, engine, catalog, snapshot_products, orders, HangingLlm())
    await container.ingest.execute()
    service = container.chat
    service._timeouts = StreamTimeouts(first_token=0.2, idle=0.2, total=0.3)
    before = sample("assistant_fallback_total", {"reason": "timeout"})
    started = asyncio.get_running_loop().time()
    result = await service.chat(None, "luminária para sala")
    elapsed = asyncio.get_running_loop().time() - started
    assert result.degraded and "Luminária Arco Dourado" in result.answer
    assert elapsed < 2.0
    events = [e.kind async for e in service.stream(None, "luminária para sala")]
    assert events == ["tool_call", "warning", "done"]
    assert sample("assistant_fallback_total", {"reason": "timeout"}) == before + 2
    await container.aclose()


async def test_failure_after_some_tokens_still_ends_with_a_clean_degraded_answer(
    settings,
    engine,
    catalog,
    snapshot_products,
    orders,  # type: ignore[no-untyped-def]
) -> None:
    container = build(settings, engine, catalog, snapshot_products, orders, DiesMidStream())
    await container.ingest.execute()
    events = [e async for e in container.chat.stream(None, "luminária para sala")]
    kinds = [e.kind for e in events]
    assert kinds == ["tool_call", "token", "token", "warning", "done"]
    assert events[-1].payload.degraded
    assert "Luminária Arco Dourado" in events[-1].payload.answer
    await container.aclose()


async def test_idle_timeout_between_tokens(
    settings,
    engine,
    catalog,
    snapshot_products,
    orders,  # type: ignore[no-untyped-def]
) -> None:
    container = build(settings, engine, catalog, snapshot_products, orders, StallsAfterFirstToken())
    await container.ingest.execute()
    container.chat._timeouts = StreamTimeouts(first_token=1.0, idle=0.15, total=5.0)
    events = [e async for e in container.chat.stream(None, "luminária para sala")]
    assert [e.kind for e in events] == ["tool_call", "token", "warning", "done"]
    assert events[-1].payload.degraded
    await container.aclose()


async def test_closing_the_stream_releases_the_model_and_books_partial_usage(
    settings,
    engine,
    catalog,
    snapshot_products,
    orders,  # type: ignore[no-untyped-def]
) -> None:
    llm = SlowTokens()
    container = build(settings, engine, catalog, snapshot_products, orders, llm)
    await container.ingest.execute()
    cancelled = sample("assistant_stream_cancelled_total")
    stream = container.chat.stream(None, "luminária para sala", user_id="user:tab")
    received = 0
    async for event in stream:
        if event.kind == "token":
            received += 1
        if received == 3:
            break
    await stream.aclose()

    assert llm.closed.is_set(), "model stream must be closed"
    assert llm.produced < 10, "generation must stop when the client leaves"
    assert sample("assistant_stream_cancelled_total") == cancelled + 1
    remaining = await container.chat._budget.remaining("any", "user:tab")  # type: ignore[union-attr]
    assert remaining["user_tokens"] < container.settings.budget_user_daily_tokens
    await container.aclose()


async def test_cancelling_the_consumer_task_releases_everything(
    settings,
    engine,
    catalog,
    snapshot_products,
    orders,  # type: ignore[no-untyped-def]
) -> None:
    llm = SlowTokens()
    container = build(settings, engine, catalog, snapshot_products, orders, llm)
    await container.ingest.execute()

    async def consume() -> None:
        async for _ in container.chat.stream(None, "luminária para sala"):
            pass

    task = asyncio.create_task(consume())
    for _ in range(100):
        if llm.produced >= 2:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(llm.closed.wait(), 2)
    await container.aclose()


async def test_http_client_disconnect_stops_generation_and_frees_the_stream_slot(
    settings,
    engine,
    catalog,
    snapshot_products,
    orders,  # type: ignore[no-untyped-def]
) -> None:
    llm = SlowTokens()
    container = build(settings, engine, catalog, snapshot_products, orders, llm)
    await container.ingest.execute()
    app = create_app(container=container)
    body = json.dumps({"message": "luminária para sala"}).encode()
    sent: list[dict] = []  # type: ignore[type-arg]
    disconnect = asyncio.Event()
    delivered = False

    async def receive():  # type: ignore[no-untyped-def]
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message):  # type: ignore[no-untyped-def]
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/chat/stream",
        "raw_path": b"/chat/stream",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json"), (b"host", b"test")],
        "client": ("127.0.0.1", 5000),
        "server": ("test", 80),
        "scheme": "http",
    }
    cancelled = sample("assistant_stream_cancelled_total")
    task = asyncio.create_task(app(scope, receive, send))
    for _ in range(200):
        if llm.produced >= 3:
            break
        await asyncio.sleep(0.01)
    assert sample("assistant_streams_active") == 1
    disconnect.set()
    await asyncio.wait_for(task, 5)

    assert llm.closed.is_set() and llm.produced < 50
    assert sample("assistant_streams_active") == 0
    assert sample("assistant_stream_cancelled_total") == cancelled + 1
    assert not any(b"event: done" in m.get("body", b"") for m in sent)
    await container.aclose()
