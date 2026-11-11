import asyncio
import random
from collections.abc import AsyncIterator, Sequence

import httpx
import pytest
from marketplace_common.resilience import (
    BreakerConfig,
    BreakerState,
    CircuitBreaker,
    Deadline,
    deadline_scope,
)

from assistant.application.ports import Prompt
from assistant.domain.errors import UpstreamUnavailable
from assistant.infrastructure.resilient import ModelGuard, ResilientEmbedder, ResilientLlm
from assistant.interface.api import create_app


class Clock:
    now = 50.0

    def __call__(self) -> float:
        return self.now


class NoSleep:
    async def __call__(self, seconds: float) -> None:
        return None


def guard(clock: Clock | None = None, timeout: float = 0.05) -> ModelGuard:
    clock = clock or Clock()
    return ModelGuard(
        f"model-{id(clock)}",
        timeout=timeout,
        breaker=CircuitBreaker(
            f"model-{id(clock)}",
            BreakerConfig(minimum_calls=3, window_size=6, open_seconds=5.0, half_open_max_calls=1),
            clock=clock,
        ),
        sleeper=NoSleep(),
        rng=random.Random(1),
    )


class FlakyLlm:
    name = "flaky"

    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0
        self.stream_started = 0
        self.hang = False

    async def generate(self, prompt: Prompt) -> str:
        self.calls += 1
        if self.hang:
            await asyncio.sleep(60)
        if self.calls <= self.failures:
            raise UpstreamUnavailable("ollama chat unavailable")
        return "answer"

    async def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        self.stream_started += 1
        if self.stream_started <= self.failures:
            raise UpstreamUnavailable("ollama chat unavailable")
        for piece in ("a", "b", "c"):
            yield piece


class FlakyEmbedder:
    name = "emb"
    dimension = 2

    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls += 1
        if self.calls <= self.failures:
            raise UpstreamUnavailable("ollama embeddings unavailable")
        return [[0.0, 1.0] for _ in texts]


PROMPT = Prompt(system="s", question="q", context=(), observations=(), text="t")


async def test_llm_retries_transient_failures() -> None:
    inner = FlakyLlm(failures=1)
    assert await ResilientLlm(inner, guard()).generate(PROMPT) == "answer"
    assert inner.calls == 2


async def test_embedder_retries_and_exposes_the_inner_metadata() -> None:
    inner = FlakyEmbedder(failures=1)
    embedder = ResilientEmbedder(inner, guard())
    assert await embedder.embed(["x", "y"]) == [[0.0, 1.0], [0.0, 1.0]]
    assert (embedder.name, embedder.dimension) == ("emb", 2)


async def test_breaker_opens_and_requests_fail_fast_with_retry_after() -> None:
    clock = Clock()
    model_guard = guard(clock)
    inner = FlakyLlm(failures=99)
    llm = ResilientLlm(inner, model_guard)
    for _ in range(2):
        with pytest.raises(UpstreamUnavailable):
            await llm.generate(PROMPT)
    assert model_guard.breaker.state is BreakerState.OPEN
    calls = inner.calls
    with pytest.raises(UpstreamUnavailable) as info:
        await llm.generate(PROMPT)
    assert inner.calls == calls and info.value.retry_after_seconds is not None
    clock.now += 5
    inner.failures = 0
    assert await llm.generate(PROMPT) == "answer"
    assert model_guard.breaker.state is BreakerState.CLOSED


async def test_slow_model_is_cut_by_the_timeout_and_the_deadline() -> None:
    inner = FlakyLlm()
    inner.hang = True
    with pytest.raises(UpstreamUnavailable):
        await ResilientLlm(inner, guard()).generate(PROMPT)
    with deadline_scope(Deadline.after(0.02)), pytest.raises(UpstreamUnavailable):
        await ResilientLlm(inner, guard(timeout=30.0)).generate(PROMPT)


async def test_stream_passes_tokens_and_failures_open_the_breaker() -> None:
    clock = Clock()
    model_guard = guard(clock)
    inner = FlakyLlm()
    llm = ResilientLlm(inner, model_guard)
    assert [piece async for piece in llm.stream(PROMPT)] == ["a", "b", "c"]
    inner.failures = 99
    for _ in range(3):
        with pytest.raises(UpstreamUnavailable):
            [piece async for piece in llm.stream(PROMPT)]
    assert model_guard.breaker.state is BreakerState.OPEN
    with pytest.raises(UpstreamUnavailable) as info:
        [piece async for piece in llm.stream(PROMPT)]
    assert info.value.retry_after_seconds is not None


async def test_api_answers_503_with_retry_after_when_the_model_is_protected() -> None:
    from fastapi import APIRouter

    app = create_app()
    router = APIRouter()

    @router.get("/boom")
    async def boom() -> None:
        raise UpstreamUnavailable("open", 7.2)

    @router.get("/legacy")
    async def legacy() -> None:
        raise UpstreamUnavailable("down")

    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        protected = await c.get("/boom")
        plain = await c.get("/legacy")
    assert protected.status_code == 503 and protected.headers["retry-after"] == "8"
    assert protected.json()["code"] == "model_unavailable"
    assert plain.status_code == 502
