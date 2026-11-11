import asyncio

import httpx
import pytest

from assistant.application.ports import Prompt
from assistant.config import Settings
from assistant.domain.errors import UpstreamUnavailable
from assistant.infrastructure.embedders.ollama import OllamaEmbedder
from assistant.infrastructure.fixtures import FixtureInventoryGateway
from assistant.infrastructure.llm.ollama import OllamaLlm
from assistant.wiring import Container, build_container
from tests.fake_ollama import FakeOllama


@pytest.fixture
async def ollama():  # type: ignore[no-untyped-def]
    server = await FakeOllama().start()
    yield server
    await server.stop()


async def _container(settings, engine, catalog, products, orders, server) -> Container:  # type: ignore[no-untyped-def]
    client = httpx.AsyncClient(timeout=5.0)
    built = build_container(
        Settings(assistant_db=settings.assistant_db, cache_enabled=False),  # type: ignore[call-arg]
        engine,
        catalog=catalog,
        inventory=FixtureInventoryGateway(products),
        orders=orders,
        embedder=OllamaEmbedder(client, "nomic-embed-text", 256, server.url),
        llm=OllamaLlm(client, "llama3.2", server.url),
        token_delay_seconds=0.0,
    )
    built.clients.append(client)
    return built


async def test_full_pipeline_runs_over_http_with_ollama_adapters(
    ollama,
    settings,
    engine,
    catalog,
    snapshot_products,
    orders,  # type: ignore[no-untyped-def]
) -> None:
    container = await _container(settings, engine, catalog, snapshot_products, orders, ollama)
    report = await container.ingest.execute()
    assert report.indexed > 0 and ollama.embed_requests >= 1
    assert container.embedder.name == "ollama-nomic-embed-text-256"

    result = await container.chat.chat(None, "luminária para sala")
    assert "Luminária Arco Dourado por R$ 289,90" in result.answer
    assert result.grounded and result.citations[0].slug == "luminaria-arco-dourado"
    assert ollama.chat_requests == 1

    events = [e async for e in container.chat.stream(None, "mochila para fazer trilha")]
    tokens = [e.payload for e in events if e.kind == "token"]
    assert len(tokens) > 3 and events[-1].payload.answer.strip() == "".join(tokens).strip()
    await container.aclose()


async def test_server_overload_degrades_to_search_results(
    ollama,
    settings,
    engine,
    catalog,
    snapshot_products,
    orders,  # type: ignore[no-untyped-def]
) -> None:
    container = await _container(settings, engine, catalog, snapshot_products, orders, ollama)
    await container.ingest.execute()
    ollama.fail_chat = 1
    result = await container.chat.chat(None, "luminária para sala")
    assert result.degraded and "Luminária Arco Dourado" in result.answer
    await container.aclose()


async def test_embedding_outage_says_the_search_is_unavailable_instead_of_not_found(
    ollama,
    settings,
    engine,
    catalog,
    snapshot_products,
    orders,  # type: ignore[no-untyped-def]
) -> None:
    container = await _container(settings, engine, catalog, snapshot_products, orders, ollama)
    await container.ingest.execute()
    ollama.fail_next = 1
    result = await container.chat.chat(None, "luminária para sala")
    assert result.degraded and "Não encontrei" not in result.answer
    assert "indisponível" in result.answer or "Não consegui" in result.answer
    assert ollama.chat_requests == 0
    await container.aclose()


async def test_adapter_errors_are_translated(ollama) -> None:  # type: ignore[no-untyped-def]
    ollama.fail_next = 2
    async with httpx.AsyncClient(timeout=2.0) as client:
        prompt = Prompt("s", "q", (), (), "texto")
        with pytest.raises(UpstreamUnavailable):
            await OllamaLlm(client, "m", ollama.url).generate(prompt)
        with pytest.raises(UpstreamUnavailable):
            await OllamaEmbedder(client, "m", 256, ollama.url).embed(["a"])
        assert await OllamaEmbedder(client, "m", 256, ollama.url).embed(["fone"])
    async with httpx.AsyncClient(timeout=1.0) as client:
        with pytest.raises(UpstreamUnavailable):
            await OllamaLlm(client, "m", "http://127.0.0.1:9").generate(prompt)


async def test_closing_the_adapter_stream_closes_the_http_connection() -> None:
    server = await FakeOllama(
        reply=lambda _: " ".join(f"p{i}" for i in range(300)), token_delay=0.01
    ).start()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            stream = OllamaLlm(client, "m", server.url).stream(Prompt("s", "q", (), (), "texto"))
            seen = []
            async for token in stream:
                seen.append(token)
                if len(seen) == 3:
                    break
            await stream.aclose()  # type: ignore[attr-defined]
            await asyncio.wait_for(server.client_closed.wait(), 2)
        assert len(seen) == 3
    finally:
        await server.stop()
