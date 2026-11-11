import pytest
from prometheus_client import REGISTRY

from marketplace_common.resilience import (
    BreakerConfig,
    BreakerState,
    CircuitBreaker,
    InMemoryTokenBucket,
    RateDecision,
    RatePolicy,
    RedisFailureMode,
    RouteRateLimiter,
)
from tests.unit.fakes import FakeClock


def backend_count(backend: str) -> float:
    return (
        REGISTRY.get_sample_value("resilience_rate_limit_backend_total", {"backend": backend})
        or 0.0
    )


def test_policy_factories() -> None:
    assert RatePolicy.per_minute(60) == RatePolicy(60, 1.0)
    assert RatePolicy.per_minute(60, burst=10) == RatePolicy(10, 1.0)
    assert RatePolicy.per_second(5) == RatePolicy(5, 5.0)
    assert RatePolicy.per_minute(0).disabled and not RatePolicy.per_minute(1).disabled


def test_token_bucket_allows_a_burst_then_refills_over_time() -> None:
    clock = FakeClock()
    bucket = InMemoryTokenBucket(clock)
    policy = RatePolicy(capacity=3, refill_per_second=1.0)
    results = [bucket.take_sync("k", policy) for _ in range(4)]
    assert [r.allowed for r in results] == [True, True, True, False]
    assert [r.remaining for r in results] == [2, 1, 0, 0]
    assert results[3].retry_after == pytest.approx(1.0)
    clock.advance(1.0)
    assert bucket.take_sync("k", policy).allowed
    assert not bucket.take_sync("k", policy).allowed
    clock.advance(100.0)
    assert bucket.take_sync("k", policy).remaining == 2


def test_token_bucket_keys_are_independent() -> None:
    bucket = InMemoryTokenBucket(FakeClock())
    policy = RatePolicy(1, 0.1)
    assert bucket.take_sync("a", policy).allowed and bucket.take_sync("b", policy).allowed
    assert not bucket.take_sync("a", policy).allowed


def test_token_bucket_reset_reports_time_to_full() -> None:
    bucket = InMemoryTokenBucket(FakeClock())
    decision = bucket.take_sync("k", RatePolicy(10, 2.0))
    assert decision.remaining == 9 and decision.reset_after == pytest.approx(0.5)


def test_idle_buckets_are_pruned_to_bound_memory() -> None:
    clock = FakeClock()
    bucket = InMemoryTokenBucket(clock, max_keys=10)
    policy = RatePolicy(2, 1.0)
    for i in range(10):
        bucket.take_sync(f"old-{i}", policy)
    clock.advance(10)
    bucket.take_sync("new", policy)
    assert len(bucket) == 1


def test_headers_on_allowed_and_limited_decisions() -> None:
    allowed = RateDecision(True, 100, 42, 0.0, 12.2, "redis")
    assert allowed.headers() == {
        "RateLimit-Limit": "100",
        "RateLimit-Remaining": "42",
        "RateLimit-Reset": "13",
    }
    limited = RateDecision(False, 100, 0, 0.2, 30.0, "redis")
    assert limited.headers()["Retry-After"] == "1"
    assert RateDecision(True, 0, 0, 0, 0, "fail_open").headers() == {}


class FakeRedisBackend:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False
        self.inner = InMemoryTokenBucket(FakeClock())

    async def take(self, key: str, policy: RatePolicy, cost: int = 1) -> RateDecision:
        self.calls += 1
        if self.fail:
            raise ConnectionError("redis down")
        return self.inner.take_sync(key, policy, cost)


def limiter(backend: FakeRedisBackend | None, mode: RedisFailureMode, **kwargs: object):  # type: ignore[no-untyped-def]
    return RouteRateLimiter(
        RatePolicy(2, 0.001),
        {"orders": RatePolicy(1, 0.001), "open": RatePolicy(0, 0)},
        primary=backend,
        fallback=InMemoryTokenBucket(FakeClock()),
        on_failure=mode,
        **kwargs,  # type: ignore[arg-type]
    )


async def test_policies_are_per_route_and_per_client() -> None:
    rl = limiter(None, RedisFailureMode.FALLBACK)
    assert [(await rl.acquire("catalog", "1.1.1.1")).allowed for _ in range(3)] == [
        True,
        True,
        False,
    ]
    assert [(await rl.acquire("orders", "1.1.1.1")).allowed for _ in range(2)] == [True, False]
    assert (await rl.acquire("catalog", "2.2.2.2")).allowed
    assert (await rl.acquire("open", "1.1.1.1")).limit == 0


async def test_uses_the_primary_while_it_is_healthy() -> None:
    backend = FakeRedisBackend()
    rl = limiter(backend, RedisFailureMode.FALLBACK)
    before = backend_count("redis")
    await rl.acquire("catalog", "c")
    assert backend.calls == 1 and backend_count("redis") == before + 1


async def test_falls_back_to_memory_when_redis_fails() -> None:
    backend = FakeRedisBackend()
    backend.fail = True
    rl = limiter(backend, RedisFailureMode.FALLBACK)
    before = backend_count("memory_fallback")
    decisions = [await rl.acquire("catalog", "c") for _ in range(3)]
    assert [d.allowed for d in decisions] == [True, True, False]
    assert backend_count("memory_fallback") == before + 3


async def test_fail_open_lets_everything_through_and_is_counted() -> None:
    backend = FakeRedisBackend()
    backend.fail = True
    rl = limiter(backend, RedisFailureMode.FAIL_OPEN)
    before = backend_count("fail_open")
    decisions = [await rl.acquire("orders", "c") for _ in range(5)]
    assert all(d.allowed and d.headers() == {} for d in decisions)
    assert backend_count("fail_open") == before + 5


async def test_fail_closed_blocks_with_retry_after() -> None:
    backend = FakeRedisBackend()
    backend.fail = True
    decision = await limiter(backend, RedisFailureMode.FAIL_CLOSED).acquire("orders", "c")
    assert not decision.allowed and decision.headers()["Retry-After"] == "1"


async def test_breaker_stops_calling_a_dead_redis_and_recovers() -> None:
    clock = FakeClock()
    backend = FakeRedisBackend()
    backend.fail = True
    breaker = CircuitBreaker(
        "rl-redis", BreakerConfig(minimum_calls=3, window_size=5, open_seconds=5.0), clock=clock
    )
    rl = limiter(backend, RedisFailureMode.FAIL_OPEN, breaker=breaker)
    for _ in range(10):
        await rl.acquire("catalog", "c")
    assert breaker.state is BreakerState.OPEN and backend.calls == 3
    backend.fail = False
    clock.advance(5)
    await rl.acquire("catalog", "c")
    await rl.acquire("catalog", "c")
    await rl.acquire("catalog", "c")
    assert breaker.state is BreakerState.CLOSED and backend.calls == 6


async def test_slow_redis_is_cut_by_the_operation_timeout() -> None:
    import asyncio

    class SlowBackend:
        async def take(self, key: str, policy: RatePolicy, cost: int = 1) -> RateDecision:
            await asyncio.sleep(5)
            raise AssertionError

    rl = RouteRateLimiter(
        RatePolicy(1, 0.001),
        primary=SlowBackend(),
        on_failure=RedisFailureMode.FAIL_OPEN,
        operation_timeout=0.01,
    )
    assert (await rl.acquire("catalog", "c")).backend == "fail_open"


async def test_decisions_metric_counts_allowed_and_limited() -> None:
    rl = limiter(None, RedisFailureMode.FALLBACK)
    for _ in range(3):
        await rl.acquire("metrics-route", "c")

    def count(result: str) -> float:
        labels = {"route": "metrics-route", "result": result}
        return REGISTRY.get_sample_value("resilience_rate_limit_decisions_total", labels) or 0.0

    assert count("allowed") == 2 and count("limited") == 1


async def test_slow_cancellation_cleanup_does_not_delay_the_answer() -> None:
    import asyncio
    import time

    class StuckBackend:
        async def take(self, key: str, policy: RatePolicy, cost: int = 1) -> RateDecision:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                await asyncio.sleep(0.3)
                raise
            raise AssertionError

    rl = RouteRateLimiter(
        RatePolicy(1, 0.001),
        primary=StuckBackend(),
        on_failure=RedisFailureMode.FAIL_OPEN,
        operation_timeout=0.02,
    )
    started = time.perf_counter()
    decision = await rl.acquire("catalog", "c")
    assert decision.backend == "fail_open" and time.perf_counter() - started < 0.25
