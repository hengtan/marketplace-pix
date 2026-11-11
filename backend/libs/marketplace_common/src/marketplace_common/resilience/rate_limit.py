from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from marketplace_common.resilience import metrics
from marketplace_common.resilience.circuit_breaker import CircuitBreaker
from marketplace_common.resilience.clock import Clock, monotonic
from marketplace_common.resilience.errors import CircuitOpenError

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

TOKEN_BUCKET_LUA = """
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
if now_ms < 0 then
  local t = redis.call('TIME')
  now_ms = t[1] * 1000 + math.floor(t[2] / 1000)
end
local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil or ts == nil then
  tokens = capacity
  ts = now_ms
end
local elapsed = math.max(0, now_ms - ts)
tokens = math.min(capacity, tokens + elapsed / 1000 * rate)
local allowed = 0
local retry_ms = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  retry_ms = math.ceil((cost - tokens) / rate * 1000)
end
redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', now_ms)
redis.call('PEXPIRE', KEYS[1], math.ceil(capacity / rate * 1000) + 1000)
local reset_ms = math.ceil((capacity - tokens) / rate * 1000)
return {allowed, math.floor(tokens), retry_ms, reset_ms}
"""


@dataclass(frozen=True, slots=True)
class RatePolicy:
    capacity: int
    refill_per_second: float

    @classmethod
    def per_minute(cls, limit: int, burst: int | None = None) -> RatePolicy:
        return cls(burst if burst is not None else limit, limit / 60.0)

    @classmethod
    def per_second(cls, limit: int, burst: int | None = None) -> RatePolicy:
        return cls(burst if burst is not None else limit, float(limit))

    @property
    def disabled(self) -> bool:
        return self.capacity <= 0 or self.refill_per_second <= 0


@dataclass(frozen=True, slots=True)
class RateDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: float
    reset_after: float
    backend: str = "memory"

    def headers(self) -> dict[str, str]:
        if self.limit <= 0:
            return {}
        headers = {
            "RateLimit-Limit": str(self.limit),
            "RateLimit-Remaining": str(max(0, self.remaining)),
            "RateLimit-Reset": str(math.ceil(self.reset_after)),
        }
        if not self.allowed:
            headers["Retry-After"] = str(max(1, math.ceil(self.retry_after)))
        return headers


UNLIMITED = RateDecision(True, 0, 0, 0.0, 0.0, "disabled")


class BucketBackend(Protocol):
    async def take(self, key: str, policy: RatePolicy, cost: int = 1) -> RateDecision: ...


class InMemoryTokenBucket:
    """Token bucket em memória, por processo. Serve de fallback e de limiter local."""

    def __init__(self, clock: Clock = monotonic, max_keys: int = 50_000) -> None:
        self._clock = clock
        self._max_keys = max_keys
        self._buckets: dict[str, tuple[float, float]] = {}

    def take_sync(self, key: str, policy: RatePolicy, cost: int = 1) -> RateDecision:
        if policy.disabled:
            return UNLIMITED
        now = self._clock()
        tokens, stamp = self._buckets.get(key, (float(policy.capacity), now))
        tokens = min(
            float(policy.capacity), tokens + max(0.0, now - stamp) * policy.refill_per_second
        )
        allowed = tokens >= cost
        retry_after = 0.0
        if allowed:
            tokens -= cost
        else:
            retry_after = (cost - tokens) / policy.refill_per_second
        self._buckets[key] = (tokens, now)
        if len(self._buckets) > self._max_keys:
            self._prune(now, policy)
        reset_after = (policy.capacity - tokens) / policy.refill_per_second
        return RateDecision(
            allowed, policy.capacity, math.floor(tokens), retry_after, reset_after, "memory"
        )

    def _prune(self, now: float, policy: RatePolicy) -> None:
        full_after = policy.capacity / policy.refill_per_second
        for key in [k for k, (_, stamp) in self._buckets.items() if now - stamp >= full_after]:
            del self._buckets[key]

    async def take(self, key: str, policy: RatePolicy, cost: int = 1) -> RateDecision:
        return self.take_sync(key, policy, cost)

    def __len__(self) -> int:
        return len(self._buckets)


class RedisTokenBucket:
    """Token bucket atômico no Redis (script Lua), com o relógio do Redis salvo `clock` injetado."""

    def __init__(self, redis: Redis, *, prefix: str = "rl", clock: Clock | None = None) -> None:
        self._redis = redis
        self._prefix = prefix
        self._clock = clock
        self._script = redis.register_script(TOKEN_BUCKET_LUA)

    async def take(self, key: str, policy: RatePolicy, cost: int = 1) -> RateDecision:
        if policy.disabled:
            return UNLIMITED
        now_ms = -1 if self._clock is None else int(self._clock() * 1000)
        allowed, remaining, retry_ms, reset_ms = await self._script(
            keys=[f"{self._prefix}:{key}"],
            args=[policy.capacity, policy.refill_per_second, now_ms, cost],
        )
        return RateDecision(
            bool(int(allowed)),
            policy.capacity,
            int(remaining),
            int(retry_ms) / 1000.0,
            int(reset_ms) / 1000.0,
            "redis",
        )


def _discard_result(task: asyncio.Future[Any]) -> None:
    if not task.cancelled():
        task.exception()


class RedisFailureMode(StrEnum):
    FALLBACK = "fallback"
    FAIL_OPEN = "fail_open"
    FAIL_CLOSED = "fail_closed"


class RouteRateLimiter:
    """Limiter por cliente e por rota. Primário no Redis; se cair, aplica o `RedisFailureMode`.

    FALLBACK usa o token bucket em memória (limite por instância), FAIL_OPEN deixa passar e
    FAIL_CLOSED bloqueia. Um circuit breaker evita pagar o timeout do Redis em toda requisição.
    """

    def __init__(
        self,
        default: RatePolicy,
        routes: Mapping[str, RatePolicy] | None = None,
        *,
        primary: BucketBackend | None = None,
        fallback: InMemoryTokenBucket | None = None,
        on_failure: RedisFailureMode = RedisFailureMode.FALLBACK,
        breaker: CircuitBreaker | None = None,
        operation_timeout: float = 0.1,
    ) -> None:
        self._default = default
        self._routes = dict(routes or {})
        self._primary = primary
        self._fallback = fallback or InMemoryTokenBucket()
        self._on_failure = on_failure
        self._breaker = breaker
        self._timeout = operation_timeout

    def policy_for(self, route: str) -> RatePolicy:
        return self._routes.get(route, self._default)

    async def acquire(self, route: str, client: str, cost: int = 1) -> RateDecision:
        policy = self.policy_for(route)
        if policy.disabled:
            return UNLIMITED
        key = f"{route}:{client}"
        decision = await self._decide(key, policy, cost)
        metrics.RATE_LIMIT_DECISIONS.labels(
            route, "allowed" if decision.allowed else "limited"
        ).inc()
        return decision

    async def _decide(self, key: str, policy: RatePolicy, cost: int) -> RateDecision:
        if self._primary is None:
            return self._fallback.take_sync(key, policy, cost)
        try:
            decision = await self._take_primary(key, policy, cost)
        except CircuitOpenError:
            return self._degraded(key, policy, cost)
        except Exception as error:
            logger.warning("rate limit backend failed: %s", type(error).__name__)
            return self._degraded(key, policy, cost)
        metrics.RATE_LIMIT_BACKEND.labels("redis").inc()
        return decision

    async def _take_primary(self, key: str, policy: RatePolicy, cost: int) -> RateDecision:
        assert self._primary is not None
        primary = self._primary

        async def operation() -> RateDecision:
            task = asyncio.ensure_future(primary.take(key, policy, cost))
            try:
                done, _ = await asyncio.wait({task}, timeout=self._timeout)
            except BaseException:
                task.cancel()
                task.add_done_callback(_discard_result)
                raise
            if not done:
                task.cancel()
                task.add_done_callback(_discard_result)
                raise TimeoutError("rate limit backend timed out")
            return task.result()

        if self._breaker is None:
            return await operation()
        return await self._breaker.call(operation)

    def _degraded(self, key: str, policy: RatePolicy, cost: int) -> RateDecision:
        if self._on_failure is RedisFailureMode.FALLBACK:
            metrics.RATE_LIMIT_BACKEND.labels("memory_fallback").inc()
            return self._fallback.take_sync(key, policy, cost)
        if self._on_failure is RedisFailureMode.FAIL_OPEN:
            metrics.RATE_LIMIT_BACKEND.labels("fail_open").inc()
            return RateDecision(True, 0, 0, 0.0, 0.0, "fail_open")
        metrics.RATE_LIMIT_BACKEND.labels("fail_closed").inc()
        return RateDecision(False, policy.capacity, 0, 1.0, 1.0, "fail_closed")
