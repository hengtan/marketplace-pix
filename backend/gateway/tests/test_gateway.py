import asyncio

import httpx
import pytest

from gateway.app import create_app
from gateway.config import Settings
from gateway.rate_limit import RateLimiter
from gateway.routes import resolve

UPSTREAMS = {
    "catalog": "http://catalog",
    "inventory": "http://inventory",
    "ordering": "http://ordering",
    "payments": "http://payments",
    "ledger": "http://ledger",
    "notifications": "http://notifications",
    "assistant": "http://assistant",
}


def settings(**overrides) -> Settings:
    base = {f"{name}_url": url for name, url in UPSTREAMS.items()}
    return Settings(_env_file=None, **{**base, **overrides})


class Recorder:
    def __init__(self, response: httpx.Response | None = None, error: Exception | None = None):
        self.requests: list[httpx.Request] = []
        self.response = response or httpx.Response(200, json={"ok": True})
        self.error = error

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.response


async def call(recorder, method, url, app_kwargs=None, **kwargs):
    app = create_app(settings(**(app_kwargs or {})), transport=httpx.MockTransport(recorder))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gw") as client:
            return await client.request(method, url, **kwargs)


@pytest.mark.parametrize(
    ("path", "service", "upstream_path"),
    [
        ("/api/catalog/products", "catalog", "/products"),
        ("/api/catalog/products/by-ids", "catalog", "/products/by-ids"),
        ("/api/catalog/categories", "catalog", "/categories"),
        ("/api/inventory/stock", "inventory", "/stock"),
        ("/api/inventory/stock/abc", "inventory", "/stock/abc"),
        ("/api/ledger/merchants/m1/summary", "ledger", "/merchants/m1/summary"),
        ("/api/ledger/reconciliation", "ledger", "/reconciliation"),
        ("/api/orders", "ordering", "/orders"),
        ("/api/orders/123", "ordering", "/orders/123"),
        ("/api/payments/by-order/9", "payments", "/payments/by-order/9"),
        ("/api/payments/dev/psp/charges/ch_1/pay", "payments", "/dev/psp/charges/ch_1/pay"),
        ("/api/notifications", "notifications", "/notifications"),
        ("/api/notifications/5/preview", "notifications", "/notifications/5/preview"),
        ("/api/assistant/chat", "assistant", "/chat"),
        ("/api/assistant/chat/stream", "assistant", "/chat/stream"),
        ("/api/assistant/evals/latest", "assistant", "/evals/latest"),
    ],
)
def test_route_table_follows_the_contract(path, service, upstream_path):
    target = resolve(path)
    assert target is not None
    assert (target.service, target.path) == (service, upstream_path)


@pytest.mark.parametrize(
    "path", ["/api", "/api/unknown", "/api/orders-evil", "/api/payments", "/health2"]
)
def test_unknown_paths_do_not_resolve(path):
    assert resolve(path) is None


async def test_forwards_method_query_body_and_idempotency_key():
    recorder = Recorder(
        httpx.Response(201, json={"id": "1"}, headers={"Idempotent-Replayed": "true"})
    )

    response = await call(
        recorder,
        "POST",
        "/api/orders?a=1&a=2",
        json={"x": 1},
        headers={"Idempotency-Key": "k-1"},
    )

    (sent,) = recorder.requests
    assert str(sent.url) == "http://ordering/orders?a=1&a=2"
    assert sent.method == "POST" and sent.headers["idempotency-key"] == "k-1"
    assert sent.content == b'{"x":1}'
    assert response.status_code == 201 and response.json() == {"id": "1"}
    assert response.headers["idempotent-replayed"] == "true"


async def test_request_id_is_created_or_reused_and_sent_upstream():
    recorder = Recorder()

    generated = await call(recorder, "GET", "/api/catalog/products")
    reused = await call(
        recorder, "GET", "/api/catalog/products", headers={"X-Request-Id": "abc-123"}
    )

    assert len(generated.headers["x-request-id"]) == 32
    assert reused.headers["x-request-id"] == "abc-123"
    assert recorder.requests[1].headers["x-request-id"] == "abc-123"


async def test_unknown_route_is_404_with_request_id():
    response = await call(Recorder(), "GET", "/api/nothing/here")
    assert response.status_code == 404 and "x-request-id" in response.headers


async def test_dev_routes_are_closed_unless_enabled():
    recorder = Recorder()
    closed = await call(recorder, "POST", "/api/payments/dev/psp/charges/ch_1/pay")
    opened = await call(
        recorder,
        "POST",
        "/api/payments/dev/psp/charges/ch_1/pay",
        app_kwargs={"enable_dev_routes": True},
    )

    assert closed.status_code == 404 and opened.status_code == 200
    assert len(recorder.requests) == 1


async def test_upstream_down_is_502_and_timeout_is_504():
    down = await call(Recorder(error=httpx.ConnectError("refused")), "GET", "/api/orders/1")
    slow = await call(Recorder(error=httpx.ReadTimeout("slow")), "GET", "/api/orders/1")

    assert down.status_code == 502 and slow.status_code == 504


async def test_upstream_error_status_is_passed_through():
    recorder = Recorder(httpx.Response(422, json={"detail": "unknown product"}))
    response = await call(recorder, "POST", "/api/orders", json={})
    assert response.status_code == 422 and response.json() == {"detail": "unknown product"}


async def test_cors_preflight_allows_the_frontend_origin_and_idempotency_key():
    response = await call(
        Recorder(),
        "OPTIONS",
        "/api/orders",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "idempotency-key,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "idempotency-key" in response.headers["access-control-allow-headers"].lower()


async def test_cors_blocks_other_origins():
    response = await call(
        Recorder(),
        "GET",
        "/api/catalog/products",
        headers={"Origin": "http://evil.example"},
    )
    assert "access-control-allow-origin" not in response.headers


async def test_exposes_idempotent_replayed_to_the_browser():
    response = await call(
        Recorder(httpx.Response(201, json={}, headers={"Idempotent-Replayed": "true"})),
        "GET",
        "/api/orders/1",
        headers={"Origin": "http://localhost:5173"},
    )
    assert "idempotent-replayed" in response.headers["access-control-expose-headers"].lower()


async def test_aggregated_health_reports_each_service():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "ledger":
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"status": "ok"})

    response = await call(handler, "GET", "/api/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["services"]["ledger"] == "down" and body["services"]["catalog"] == "ok"


async def test_aggregated_health_is_ok_when_everything_is_up():
    response = await call(Recorder(httpx.Response(200, json={})), "GET", "/api/health")
    assert response.status_code == 200 and response.json()["status"] == "ok"


async def test_rate_limit_returns_429_with_retry_after():
    ticks = {"now": 0.0}
    limiter = RateLimiter(2, window_seconds=60, clock=lambda: ticks["now"])
    app = create_app(settings(), transport=httpx.MockTransport(Recorder()), rate_limiter=limiter)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gw") as c,
    ):
        codes = [(await c.get("/api/catalog/products")).status_code for _ in range(3)]
        blocked = await c.get("/api/catalog/products")
        ticks["now"] = 61.0
        after = await c.get("/api/catalog/products")

    assert codes == [200, 200, 429]
    assert blocked.headers["retry-after"].isdigit()
    assert after.status_code == 200


def test_rate_limiter_is_per_client_and_disabled_with_zero():
    limiter = RateLimiter(1, clock=lambda: 0.0)
    assert limiter.check("a") is None and limiter.check("a") is not None
    assert limiter.check("b") is None
    assert RateLimiter(0).check("a") is None


async def test_traceparent_and_request_id_are_forwarded_upstream():
    recorder = Recorder()
    traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

    response = await call(
        recorder,
        "GET",
        "/api/catalog/products",
        headers={"traceparent": traceparent, "X-Request-Id": "req-1"},
    )

    (forwarded,) = recorder.requests
    assert forwarded.headers["traceparent"] == traceparent
    assert forwarded.headers["x-request-id"] == "req-1"
    assert response.headers["x-request-id"] == "req-1"


async def test_event_stream_is_forwarded_chunk_by_chunk_without_buffering():
    gate = asyncio.Event()

    async def upstream_body():
        yield b"event: token\ndata: one\n\n"
        await gate.wait()
        yield b"event: done\ndata: {}\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=upstream_body()
        )

    app = create_app(settings(), transport=httpx.MockTransport(handler))
    sent: list[dict] = []

    delivered = False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": b"{}", "more_body": False}
        await asyncio.Event().wait()

    async def send(message):
        sent.append(message)
        if message["type"] == "http.response.body" and message.get("body"):
            gate.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/api/assistant/chat/stream",
        "raw_path": b"/api/assistant/chat/stream",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "client": ("127.0.0.1", 1234),
        "server": ("gw", 80),
        "scheme": "http",
    }
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(app(scope, receive, send), timeout=5)

    start = next(m for m in sent if m["type"] == "http.response.start")
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert headers["content-type"].startswith("text/event-stream")
    assert "x-request-id" in headers and headers["x-accel-buffering"] == "no"
    assert body == b"event: token\ndata: one\n\nevent: done\ndata: {}\n\n"
