from contextlib import asynccontextmanager

import httpx
import pytest
from marketplace_common.resilience import (
    InMemoryTokenBucket,
    RateDecision,
    RatePolicy,
    RedisFailureMode,
    RouteRateLimiter,
)
from test_gateway import Recorder, settings

from gateway.app import create_app
from gateway.config import Settings


class Script:
    def __init__(self, *outcomes: httpx.Response | Exception) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class NoSleep:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


@asynccontextmanager
async def Client(handler, cfg: Settings | None = None, **kwargs):  # type: ignore[no-untyped-def]  # noqa: N802
    app = create_app(
        cfg or settings(), transport=httpx.MockTransport(handler), sleeper=NoSleep(), **kwargs
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw") as client,
    ):
        yield client


def ok(body: dict | None = None) -> httpx.Response:
    return httpx.Response(200, json=body or {"ok": True})


async def test_get_is_retried_on_transient_failures_but_post_is_not() -> None:
    script = Script(httpx.ConnectError("boom"), httpx.Response(503), ok())
    async with Client(script) as c:
        response = await c.get("/api/catalog/products")
    assert response.status_code == 200 and len(script.requests) == 3

    script = Script(httpx.ConnectError("boom"), ok())
    async with Client(script) as c:
        response = await c.post("/api/orders", json={}, headers={"Idempotency-Key": "k"})
    assert response.status_code == 502 and len(script.requests) == 1


async def test_retries_stop_after_the_configured_attempts() -> None:
    script = Script(httpx.Response(503, json={"detail": "busy"}, headers={"Retry-After": "3"}))
    async with Client(script, settings(retry_attempts=3)) as c:
        response = await c.get("/api/catalog/products")
    assert response.status_code == 503 and len(script.requests) == 3
    assert response.json() == {"detail": "busy"} and response.headers["retry-after"] == "3"


async def test_circuit_opens_and_the_catalog_answers_503_fast_without_calling_upstream() -> None:
    script = Script(httpx.ConnectError("down"))
    cfg = settings(breaker_minimum_calls=4, breaker_window_size=8, retry_attempts=1)
    async with Client(script, cfg) as c:
        first = [(await c.get("/api/catalog/products")).status_code for _ in range(4)]
        calls_before = len(script.requests)
        blocked = await c.get("/api/catalog/products")
        calls_after = len(script.requests)
        other = await c.get("/api/inventory/stock")
        health = await c.get("/api/health")
    assert first == [502, 502, 502, 502]
    assert blocked.status_code == 503 and calls_after == calls_before
    body = blocked.json()
    assert body["code"] == "circuit_open" and body["service"] == "catalog"
    assert body["detail"] == "catalog is temporarily unavailable"
    assert (
        blocked.headers["retry-after"] == str(body["retry_after_seconds"])
        and body["retry_after_seconds"] >= 1
    )
    assert other.status_code == 502
    assert health.json()["breakers"]["catalog"]["state"] == "open"
    assert health.json()["status"] == "degraded"


async def test_breaker_counts_5xx_responses_as_failures() -> None:
    script = Script(httpx.Response(500, json={"detail": "bug"}))
    cfg = settings(breaker_minimum_calls=3, breaker_window_size=6, retry_attempts=1)
    async with Client(script, cfg) as c:
        codes = [(await c.get("/api/ledger/reconciliation")).status_code for _ in range(5)]
    assert codes == [500, 500, 500, 503, 503]


async def test_client_errors_do_not_trip_the_breaker() -> None:
    script = Script(httpx.Response(404, json={"detail": "nope"}))
    cfg = settings(breaker_minimum_calls=3, breaker_window_size=6)
    async with Client(script, cfg) as c:
        codes = [(await c.get("/api/catalog/products/x")).status_code for _ in range(8)]
    assert set(codes) == {404}


async def test_deadline_is_forwarded_and_shrinks_with_each_hop() -> None:
    recorder = Recorder()
    async with Client(recorder, settings(request_deadline_seconds=5.0)) as c:
        await c.get("/api/catalog/products")
        await c.get("/api/catalog/products", headers={"X-Request-Deadline": "1500"})
    default, explicit = recorder.requests
    assert 4000 < int(default.headers["x-request-deadline"]) <= 5000
    assert 1000 < int(explicit.headers["x-request-deadline"]) <= 1500


async def test_client_deadline_is_capped_by_the_gateway_ceiling() -> None:
    recorder = Recorder()
    async with Client(recorder, settings(max_request_deadline_seconds=2.0)) as c:
        await c.get("/api/catalog/products", headers={"X-Request-Deadline": "60000"})
    assert int(recorder.requests[0].headers["x-request-deadline"]) <= 2000


async def test_expired_deadline_fails_fast_with_504() -> None:
    recorder = Recorder()
    async with Client(recorder) as c:
        response = await c.get("/api/catalog/products", headers={"X-Request-Deadline": "0"})
    assert response.status_code == 504 and recorder.requests == []


async def test_upstream_timeout_is_clamped_to_the_remaining_budget() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.extensions["timeout"]))
        return ok()

    async with Client(handler, settings(upstream_timeout=10.0, request_deadline_seconds=2.0)) as c:
        await c.get("/api/catalog/products")
    assert seen[0]["read"] <= 2.0


async def test_bulkhead_rejects_with_503_when_a_service_is_saturated() -> None:
    import asyncio

    release = asyncio.Event()

    async def slow(request: httpx.Request) -> httpx.Response:
        await release.wait()
        return ok()

    cfg = settings(bulkhead_max_concurrent=1, bulkhead_max_queue=0)
    async with Client(slow, cfg) as c:
        running = asyncio.create_task(c.get("/api/catalog/products"))
        await asyncio.sleep(0.01)
        rejected = await c.get("/api/catalog/products")
        other_service = asyncio.create_task(c.get("/api/inventory/stock"))
        await asyncio.sleep(0.01)
        release.set()
        assert (await running).status_code == 200
        assert (await other_service).status_code == 200
    assert rejected.status_code == 503 and rejected.json()["code"] == "overloaded"
    assert rejected.headers["retry-after"]


async def test_rate_limit_headers_on_success_and_429() -> None:
    cfg = settings(rate_limit_per_minute=2, rate_limit_routes={})
    async with Client(Recorder(), cfg) as c:
        first = await c.get("/api/catalog/products")
        await c.get("/api/catalog/products")
        limited = await c.get("/api/catalog/products")
    assert first.headers["ratelimit-limit"] == "2" and first.headers["ratelimit-remaining"] == "1"
    assert limited.status_code == 429 and limited.headers["ratelimit-remaining"] == "0"
    assert int(limited.headers["retry-after"]) >= 1 and int(limited.headers["ratelimit-reset"]) >= 1


async def test_rate_limit_is_configurable_per_route() -> None:
    cfg = settings(rate_limit_per_minute=100, rate_limit_routes={"ordering": 1})
    async with Client(Recorder(), cfg) as c:
        orders = [(await c.get("/api/orders/1")).status_code for _ in range(2)]
        catalog = [(await c.get("/api/catalog/products")).status_code for _ in range(5)]
    assert orders == [200, 429] and set(catalog) == {200}


class BrokenRedis:
    async def take(self, key: str, policy: RatePolicy, cost: int = 1) -> RateDecision:
        raise ConnectionError("redis down")


def limiter(mode: RedisFailureMode) -> RouteRateLimiter:
    return RouteRateLimiter(
        RatePolicy(1, 0.001), primary=BrokenRedis(), fallback=InMemoryTokenBucket(), on_failure=mode
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (RedisFailureMode.FALLBACK, [200, 429, 429]),
        (RedisFailureMode.FAIL_OPEN, [200, 200, 200]),
        (RedisFailureMode.FAIL_CLOSED, [429, 429, 429]),
    ],
)
async def test_gateway_keeps_answering_when_redis_is_down(mode, expected) -> None:  # type: ignore[no-untyped-def]
    async with Client(Recorder(), rate_limiter=limiter(mode)) as c:
        codes = [(await c.get("/api/catalog/products")).status_code for _ in range(3)]
    assert codes == expected


async def test_two_gateway_instances_share_the_redis_bucket() -> None:
    import os

    from redis.asyncio import Redis

    url = os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/15")
    probe = Redis.from_url(url)
    try:
        await probe.ping()
    except Exception:
        pytest.skip("redis not available")
    await probe.delete("gw:rl:catalog:127.0.0.1")
    await probe.aclose()

    cfg = settings(redis_url=url, rate_limit_per_minute=3, rate_limit_routes={})
    codes: list[int] = []
    async with Client(Recorder(), cfg) as first, Client(Recorder(), cfg) as second:
        for i in range(5):
            target = first if i % 2 == 0 else second
            codes.append((await target.get("/api/catalog/products")).status_code)
    assert codes == [200, 200, 200, 429, 429]


async def test_assistant_gets_a_longer_default_deadline_but_explicit_headers_win() -> None:
    recorder = Recorder()
    cfg = settings(request_deadline_seconds=2.0, service_deadlines={"assistant": 20.0})
    async with Client(recorder, cfg) as c:
        await c.post("/api/assistant/chat", json={})
        await c.post("/api/assistant/chat", json={}, headers={"X-Request-Deadline": "3000"})
        await c.get("/api/catalog/products")
    long_default, explicit, other = recorder.requests
    assert 15000 < int(long_default.headers["x-request-deadline"]) <= 20000
    assert 2000 < int(explicit.headers["x-request-deadline"]) <= 3000
    assert int(other.headers["x-request-deadline"]) <= 2000
