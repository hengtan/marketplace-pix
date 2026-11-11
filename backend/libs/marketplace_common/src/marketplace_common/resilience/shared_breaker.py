from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from marketplace_common.resilience.circuit_breaker import (
    BreakerConfig,
    BreakerState,
    CircuitBreaker,
    FailurePredicate,
    _any_exception,
    _Permit,
)
from marketplace_common.resilience.clock import Clock, monotonic

logger = logging.getLogger(__name__)


BreakerRedis = Any


class SharedCircuitBreaker(CircuitBreaker):
    """Disjuntor que compartilha entre as réplicas a decisão de abrir.

    Quando uma réplica abre, grava no Redis uma chave que vive `open_seconds`. As outras leem a
    chave (no máximo a cada `sync_interval`) e abrem também, com o tempo restante. Quem fecha apaga
    a chave. A janela de falhas e a contagem de sondas do half-open continuam locais, e se o Redis
    falha o disjuntor volta a ser o local, sem derrubar a chamada.
    """

    def __init__(
        self,
        name: str,
        config: BreakerConfig | None,
        redis: BreakerRedis,
        *,
        prefix: str = "cb:",
        sync_interval: float = 0.25,
        clock: Clock = monotonic,
        is_failure: FailurePredicate = _any_exception,
    ) -> None:
        super().__init__(name, config, clock=clock, is_failure=is_failure)
        self._redis = redis
        self._key = f"{prefix}{name}"
        self._sync_interval = sync_interval
        self._next_sync = 0.0
        self._publish: BreakerState | None = None

    def _transition(self, to: BreakerState) -> None:
        previous = self._state
        super()._transition(to)
        if to is not previous and to in (BreakerState.OPEN, BreakerState.CLOSED):
            self._publish = to

    async def _sync_from_shared(self) -> None:
        now = self._clock()
        if now < self._next_sync:
            return
        self._next_sync = now + self._sync_interval
        if self._state is not BreakerState.CLOSED:
            return
        try:
            remaining_ms = await self._redis.pttl(self._key)
        except Exception:
            logger.warning("shared breaker '%s' unavailable, using the local state", self.name)
            return
        if remaining_ms > 0:
            self._transition(BreakerState.OPEN)
            self._publish = None
            self._opened_at = now - (self.config.open_seconds - remaining_ms / 1000.0)

    async def _push_shared(self) -> None:
        state, self._publish = self._publish, None
        if state is None:
            return
        try:
            if state is BreakerState.OPEN:
                await self._redis.set(self._key, "1", px=int(self.config.open_seconds * 1000))
            else:
                await self._redis.delete(self._key)
        except Exception:
            logger.warning("shared breaker '%s' unavailable, state stays local", self.name)

    @asynccontextmanager
    async def guard(self) -> AsyncIterator[_Permit]:
        await self._sync_from_shared()
        try:
            async with super().guard() as permit:
                yield permit
        finally:
            await self._push_shared()
