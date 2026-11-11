import logging
from collections.abc import AsyncIterator
from dataclasses import replace

import httpx
import pytest

from assistant.application.ports import Prompt
from assistant.config import Settings
from assistant.infrastructure.fixtures import FixtureInventoryGateway
from assistant.infrastructure.llm.mock import MockLlm
from assistant.infrastructure.logging_pii import install_pii_redaction
from assistant.interface.api import create_app
from assistant.wiring import Container, build_container
from tests.attacks import DIRECT_ATTACKS, INDIRECT_ATTACKS


class ParrotLlm(MockLlm):
    """Worst case model: repeats whatever is in its context, instructions included."""

    name = "parrot"

    async def generate(self, prompt: Prompt) -> str:
        body = "\n".join(item.passage.content for item in prompt.context)
        return f"{body} [1]"

    async def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        yield await self.generate(prompt)


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


def _container(settings, engine, catalog, products, orders, llm) -> Container:  # type: ignore[no-untyped-def]
    return build_container(
        settings,
        engine,
        catalog=catalog,
        inventory=FixtureInventoryGateway(products),
        orders=orders,
        llm=llm,
        token_delay_seconds=0.0,
    )


@pytest.mark.parametrize(
    ("name", "fields", "payload"), INDIRECT_ATTACKS, ids=[a[0] for a in INDIRECT_ATTACKS]
)
async def test_poisoned_catalog_text_cannot_steer_even_a_parrot_model(
    name,
    fields,
    payload,
    settings,
    engine,
    catalog,
    snapshot_products,
    orders,  # type: ignore[no-untyped-def]
) -> None:
    update = dict(fields)
    if "tags" in update:
        update["tags"] = tuple(update["tags"].split(";"))  # type: ignore[assignment]
    catalog.products = [
        replace(p, **update) if p.slug == "fone-bluetooth-nova" else p for p in catalog.products
    ]
    container = _container(settings, engine, catalog, snapshot_products, orders, ParrotLlm())
    try:
        report = await container.ingest.execute()
        assert report.flagged >= 1, name
        result = await container.chat.chat(None, "quero um fone com cancelamento de ruído")
        assert any(p.slug == "fone-bluetooth-nova" for p in result.retrieved), "still findable"
        everything = (result.answer + " " + " ".join(p.content for p in result.retrieved)).lower()
        assert payload.lower() not in everything, name
        assert "http" not in result.answer.lower()
    finally:
        await container.aclose()


@pytest.mark.parametrize(
    ("name", "text", "level"),
    [a for a in DIRECT_ATTACKS if a[2] == "block"],
    ids=[a[0] for a in DIRECT_ATTACKS if a[2] == "block"],
)
async def test_blocked_attacks_never_reach_the_agent_or_the_model(
    name,
    text,
    level,
    settings,
    engine,
    catalog,
    snapshot_products,
    orders,  # type: ignore[no-untyped-def]
) -> None:
    llm = CountingLlm()
    container = _container(settings, engine, catalog, snapshot_products, orders, llm)
    try:
        await container.ingest.execute()
        result = await container.chat.chat(None, text)
        assert result.answer.startswith("Não posso seguir"), name
        assert result.tool_calls == [] and result.retrieved == [] and llm.calls == 0
    finally:
        await container.aclose()


async def test_session_flood_hits_the_budget_and_returns_429(
    settings,
    engine,
    catalog,
    snapshot_products,
    orders,  # type: ignore[no-untyped-def]
) -> None:
    tight = Settings(  # type: ignore[call-arg]
        assistant_db=settings.assistant_db, cache_enabled=False, budget_session_tokens=1500
    )
    container = _container(tight, engine, catalog, snapshot_products, orders, MockLlm())
    await container.ingest.execute()
    app = create_app(container=container)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = (await client.post("/chat", json={"message": "luminária para sala"})).json()
        body = {"session_id": first["session_id"], "message": "luminária para sala"}
        statuses = [(await client.post("/chat", json=body)).status_code for _ in range(6)]
        assert statuses[0] == 200 and 429 in statuses
        blocked = await client.post("/chat", json=body)
        assert blocked.status_code == 429 and blocked.headers["retry-after"]
        assert blocked.json()["scope"] == "session"
        other = await client.post("/chat", json={"message": "luminária para sala"})
        assert other.status_code == 200
        stream = await client.post("/chat/stream", json=body)
        assert "event: error" in stream.text and "budget exceeded" in stream.text
    await container.aclose()


async def test_user_budget_follows_the_user_across_sessions(
    settings,
    engine,
    catalog,
    snapshot_products,
    orders,  # type: ignore[no-untyped-def]
) -> None:
    tight = Settings(  # type: ignore[call-arg]
        assistant_db=settings.assistant_db, cache_enabled=False, budget_user_daily_tokens=1500
    )
    container = _container(tight, engine, catalog, snapshot_products, orders, MockLlm())
    await container.ingest.execute()
    app = create_app(container=container)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        heavy = {"x-user-id": "attacker"}
        codes = [
            (
                await client.post("/chat", json={"message": "luminária para sala"}, headers=heavy)
            ).status_code
            for _ in range(6)
        ]
        assert codes[0] == 200 and codes[-1] == 429
        calm = await client.post(
            "/chat", json={"message": "luminária para sala"}, headers={"x-user-id": "other"}
        )
        assert calm.status_code == 200
    await container.aclose()


async def test_personal_data_in_a_question_never_reaches_the_logs(
    indexed,
    caplog: pytest.LogCaptureFixture,  # type: ignore[no-untyped-def]
) -> None:
    install_pii_redaction()
    caplog.set_level(logging.DEBUG)
    await indexed.chat.chat(
        None, "meu cpf é 529.982.247-25 e meu email é ana@loja.com, quero um fone"
    )
    assert "529.982" not in caplog.text and "ana@loja.com" not in caplog.text
