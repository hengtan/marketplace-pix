from __future__ import annotations

import logging
import math
from collections.abc import Awaitable
from typing import Protocol

from marketplace_common.resilience.clock import Clock, monotonic

logger = logging.getLogger(__name__)

MAX_EXPONENT = 30
MAX_MEMORY_KEYS = 50_000


class BackoffRedis(Protocol):
    def incr(self, key: str) -> Awaitable[int]: ...

    def expire(self, key: str, seconds: int) -> Awaitable[object]: ...

    def set(self, key: str, value: str, ex: int | None = None) -> Awaitable[object]: ...

    def pttl(self, key: str) -> Awaitable[int]: ...

    def delete(self, *keys: str) -> Awaitable[int]: ...


class ProgressiveBackoff:
    """Espera progressiva por chave. Cada falha consecutiva dobra o bloqueio (base, 2x, 4x...) até
    o teto; um sucesso zera. O estado vive no Redis, então vale para todas as instâncias; se o
    Redis falha, cai para a memória do processo (por instância) em vez de deixar de proteger."""

    def __init__(
        self,
        redis: BackoffRedis | None = None,
        *,
        prefix: str = "auth:backoff:",
        base_seconds: float = 2.0,
        max_seconds: float = 900.0,
        memory_seconds: float = 3600.0,
        clock: Clock = monotonic,
    ) -> None:
        self._redis = redis
        self._prefix = prefix
        self._base = base_seconds
        self._max = max_seconds
        self._memory_seconds = memory_seconds
        self._clock = clock
        self._local: dict[str, tuple[int, float, float]] = {}

    def delay_for(self, failures: int) -> float:
        growth = float(2 ** min(failures - 1, MAX_EXPONENT))
        return min(self._base * growth, self._max)

    async def blocked_for(self, key: str) -> float:
        if self._redis is not None:
            try:
                ms = await self._redis.pttl(f"{self._prefix}block:{key}")
            except Exception:
                logger.warning("backoff store unavailable, using process memory")
            else:
                return float(ms) / 1000.0 if ms > 0 else 0.0
        return self._local_blocked(key)

    async def record_failure(self, key: str) -> float:
        if self._redis is not None:
            try:
                failures = await self._redis.incr(f"{self._prefix}fail:{key}")
                await self._redis.expire(
                    f"{self._prefix}fail:{key}", math.ceil(self._memory_seconds)
                )
                delay = self.delay_for(failures)
                await self._redis.set(
                    f"{self._prefix}block:{key}", "1", ex=max(1, math.ceil(delay))
                )
                return delay
            except Exception:
                logger.warning("backoff store unavailable, using process memory")
        return self._local_failure(key)

    async def reset(self, key: str) -> None:
        self._local.pop(key, None)
        if self._redis is not None:
            try:
                await self._redis.delete(f"{self._prefix}fail:{key}", f"{self._prefix}block:{key}")
            except Exception:
                logger.warning("backoff store unavailable, could not reset")

    def _local_blocked(self, key: str) -> float:
        entry = self._local.get(key)
        if entry is None:
            return 0.0
        return max(0.0, entry[2] - self._clock())

    def _local_failure(self, key: str) -> float:
        now = self._clock()
        failures, forget_at, _ = self._local.get(key, (0, 0.0, 0.0))
        if forget_at <= now:
            failures = 0
        failures += 1
        delay = self.delay_for(failures)
        if len(self._local) >= MAX_MEMORY_KEYS:
            self._local = {k: v for k, v in self._local.items() if v[1] > now}
        self._local[key] = (failures, now + self._memory_seconds, now + delay)
        return delay
