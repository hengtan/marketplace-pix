from __future__ import annotations

import random

import httpx
from marketplace_common.resilience import (
    BreakerConfig,
    BreakerRegistry,
    Bulkhead,
    CircuitBreaker,
    ResilienceError,
    RetryBudget,
    RetryPolicy,
    is_idempotent_method,
    retry_async,
)
from marketplace_common.resilience.clock import Sleeper, sleep

from gateway.config import Settings

RETRYABLE_STATUS = frozenset({502, 503, 504})


def _is_breaker_failure(error: BaseException) -> bool:
    return not isinstance(error, ResilienceError)


def _is_transport_error(error: BaseException) -> bool:
    return isinstance(error, httpx.TransportError)


class UpstreamGuard:
    """Chamadas aos serviços com retry (só leituras), circuit breaker e bulkhead por serviço."""

    def __init__(
        self,
        settings: Settings,
        services: list[str],
        *,
        sleeper: Sleeper = sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.registry = BreakerRegistry()
        self._sleeper = sleeper
        self._rng = rng
        self._policy = RetryPolicy(
            max_attempts=settings.retry_attempts,
            base_delay=settings.retry_base_delay,
            max_delay=settings.retry_max_delay,
        )
        config = BreakerConfig(
            failure_rate_threshold=settings.breaker_failure_rate,
            slow_call_threshold=settings.breaker_slow_call_seconds,
            minimum_calls=settings.breaker_minimum_calls,
            window_size=settings.breaker_window_size,
            window_seconds=settings.breaker_window_seconds,
            open_seconds=settings.breaker_open_seconds,
            half_open_max_calls=settings.breaker_half_open_calls,
        )
        self._breakers: dict[str, CircuitBreaker] = {
            name: self.registry.get(name, config, is_failure=_is_breaker_failure)
            for name in services
        }
        self._bulkheads = {
            name: Bulkhead(
                name,
                settings.bulkhead_max_concurrent,
                settings.bulkhead_max_queue,
                settings.bulkhead_queue_timeout,
            )
            for name in services
        }
        self._budgets = {name: RetryBudget(ratio=settings.retry_budget_ratio) for name in services}

    def snapshot(self) -> dict[str, dict[str, object]]:
        return dict(self.registry.snapshot())

    def all_closed(self) -> bool:
        return all(s["state"] == "closed" for s in self.registry.snapshot().values())

    async def send(
        self, client: httpx.AsyncClient, service: str, request: httpx.Request
    ) -> httpx.Response:
        breaker = self._breakers[service]
        bulkhead = self._bulkheads[service]

        async def attempt() -> httpx.Response:
            async def guarded() -> httpx.Response:
                async with bulkhead.slot():
                    return await self._roundtrip(client, request)

            return await breaker.call(guarded, failure_on_result=lambda r: r.status_code >= 500)

        return await retry_async(
            attempt,
            name=f"gateway-{service}",
            idempotent=is_idempotent_method(request.method),
            policy=self._policy,
            retry_on=_is_transport_error,
            retry_on_result=lambda r: r.status_code in RETRYABLE_STATUS,
            budget=self._budgets[service],
            rng=self._rng,
            sleeper=self._sleeper,
        )

    @staticmethod
    async def _roundtrip(client: httpx.AsyncClient, request: httpx.Request) -> httpx.Response:
        upstream = await client.send(request, stream=True)
        if upstream.headers.get("content-type", "").startswith("text/event-stream"):
            return upstream
        try:
            await upstream.aread()
        finally:
            await upstream.aclose()
        return upstream
