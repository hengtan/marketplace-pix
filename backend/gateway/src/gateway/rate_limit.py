from __future__ import annotations

from typing import Protocol

from marketplace_common.resilience import (
    BreakerConfig,
    CircuitBreaker,
    InMemoryTokenBucket,
    RateDecision,
    RatePolicy,
    RedisTokenBucket,
    RouteRateLimiter,
)
from marketplace_common.resilience.clock import Clock, monotonic
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from gateway.config import Settings


class Limiter(Protocol):
    async def acquire(self, route: str, client: str, cost: int = 1) -> RateDecision: ...


class RateLimiter:
    """Limiter simples em memória, mesma regra do token bucket usado no Redis (uma política só)."""

    def __init__(self, limit: int, window_seconds: float = 60.0, clock: Clock = monotonic) -> None:
        self._policy = RatePolicy(limit, limit / window_seconds)
        self._bucket = InMemoryTokenBucket(clock)

    def check(self, key: str) -> float | None:
        """Devolve None se permitido, ou os segundos até poder tentar de novo."""
        decision = self._bucket.take_sync(key, self._policy)
        return None if decision.allowed else decision.retry_after

    async def acquire(self, route: str, client: str, cost: int = 1) -> RateDecision:
        return self._bucket.take_sync(f"{route}:{client}", self._policy, cost)


def build_redis(settings: Settings) -> Redis | None:
    if not settings.redis_url:
        return None
    timeout = settings.rate_limit_redis_timeout
    return Redis.from_url(
        settings.redis_url,
        socket_timeout=timeout,
        socket_connect_timeout=timeout,
        max_connections=200,
        retry=Retry(NoBackoff(), 0),
    )


def build_limiter(settings: Settings, redis: Redis | None) -> RouteRateLimiter:
    breaker = None
    primary = None
    if redis is not None:
        primary = RedisTokenBucket(redis, prefix="gw:rl")
        breaker = CircuitBreaker(
            "rate-limit-redis",
            BreakerConfig(
                minimum_calls=10, window_size=30, open_seconds=5.0, half_open_max_calls=3
            ),
        )
    return RouteRateLimiter(
        RatePolicy.per_minute(settings.rate_limit_per_minute),
        {
            route: RatePolicy.per_minute(limit)
            for route, limit in settings.rate_limit_routes.items()
        },
        primary=primary,
        on_failure=settings.rate_limit_failure_mode,
        breaker=breaker,
        operation_timeout=settings.rate_limit_redis_timeout,
    )
