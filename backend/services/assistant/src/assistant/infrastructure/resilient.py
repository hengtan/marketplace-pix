from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

from marketplace_common.resilience import (
    BreakerConfig,
    Bulkhead,
    CircuitBreaker,
    ResilienceError,
    RetryBudget,
    RetryPolicy,
    cap_timeout,
    retry_async,
)
from marketplace_common.resilience.clock import Sleeper, sleep

from assistant.application.ports import Embedder, LlmClient, Prompt
from assistant.domain.errors import UpstreamUnavailable


def _is_transient(error: BaseException) -> bool:
    return isinstance(error, UpstreamUnavailable | TimeoutError | ConnectionError | OSError)


class ModelGuard:
    """Timeout, retry, circuit breaker e bulkhead para chamadas ao modelo (LLM ou embedder)."""

    def __init__(
        self,
        name: str,
        *,
        timeout: float,
        breaker: CircuitBreaker | None = None,
        bulkhead: Bulkhead | None = None,
        retry_policy: RetryPolicy | None = None,
        budget: RetryBudget | None = None,
        sleeper: Sleeper = sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.name = name
        self._timeout = timeout
        self.breaker = breaker or CircuitBreaker(
            name, BreakerConfig(minimum_calls=4, window_size=8, open_seconds=20.0)
        )
        self._bulkhead = bulkhead or Bulkhead(name, max_concurrent=4, max_queue=4)
        self._policy = retry_policy or RetryPolicy(max_attempts=2, base_delay=0.2, max_delay=1.0)
        self._budget = budget or RetryBudget()
        self._sleeper = sleeper
        self._rng = rng

    @staticmethod
    def _unavailable(error: ResilienceError) -> UpstreamUnavailable:
        return UpstreamUnavailable(str(error), max(1.0, error.retry_after_seconds))

    async def call[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        async def attempt() -> T:
            async def guarded() -> T:
                async with self._bulkhead.slot(), asyncio.timeout(cap_timeout(self._timeout)):
                    return await operation()

            return await self.breaker.call(guarded)

        try:
            return await retry_async(
                attempt,
                name=self.name,
                idempotent=True,
                policy=self._policy,
                retry_on=_is_transient,
                budget=self._budget,
                rng=self._rng,
                sleeper=self._sleeper,
            )
        except ResilienceError as error:
            raise self._unavailable(error) from error
        except TimeoutError as error:
            raise UpstreamUnavailable(f"{self.name} timed out", 1.0) from error

    async def stream(self, source: AsyncIterator[str]) -> AsyncIterator[str]:
        try:
            async with self.breaker.guard(), self._bulkhead.slot():
                async for piece in source:
                    yield piece
        except ResilienceError as error:
            raise self._unavailable(error) from error


class ResilientLlm:
    def __init__(self, inner: LlmClient, guard: ModelGuard) -> None:
        self._inner = inner
        self._guard = guard

    @property
    def name(self) -> str:
        return self._inner.name

    async def generate(self, prompt: Prompt) -> str:
        return await self._guard.call(lambda: self._inner.generate(prompt))

    def stream(self, prompt: Prompt) -> AsyncIterator[str]:
        return self._guard.stream(self._inner.stream(prompt))


class ResilientEmbedder:
    def __init__(self, inner: Embedder, guard: ModelGuard) -> None:
        self._inner = inner
        self._guard = guard

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def dimension(self) -> int:
        return self._inner.dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._guard.call(lambda: self._inner.embed(texts))
