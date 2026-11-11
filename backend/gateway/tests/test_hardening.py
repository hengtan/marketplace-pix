from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest

from tests.test_gateway import Recorder, settings
from tests.test_resilience import Client

EXPECTED = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "cross-origin-resource-policy": "same-site",
}


def assert_hardened(response: httpx.Response) -> None:
    for name, value in EXPECTED.items():
        assert response.headers.get(name) == value, name
    assert "strict-transport-security" not in response.headers


async def test_security_headers_are_on_proxied_and_generated_responses() -> None:
    async with Client(Recorder(), settings(rate_limit_per_minute=100)) as client:
        assert_hardened(await client.get("/api/catalog/products"))
        assert_hardened(await client.get("/api/nothing/here"))
        assert_hardened(await client.get("/health"))
        assert_hardened(await client.get("/api/auth/me"))
        preflight = await client.options(
            "/api/catalog/products",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert_hardened(preflight)
        assert preflight.headers["access-control-allow-origin"] == "http://localhost:5173"


async def test_security_headers_are_on_rate_limited_responses() -> None:
    cfg = settings(rate_limit_per_minute=1, rate_limit_routes={})
    async with Client(Recorder(), cfg) as client:
        await client.get("/api/catalog/products")
        limited = await client.get("/api/catalog/products")
    assert limited.status_code == 429
    assert_hardened(limited)


async def test_the_gateway_overrides_what_an_upstream_says() -> None:
    upstream = httpx.Response(
        200, json={}, headers={"X-Content-Type-Options": "sniff", "Referrer-Policy": "unsafe-url"}
    )
    async with Client(Recorder(upstream), settings()) as client:
        response = await client.get("/api/catalog/products")
    assert_hardened(response)
    assert response.headers.get_list("x-content-type-options") == ["nosniff"]


async def test_hsts_is_off_by_default_and_on_with_the_flag() -> None:
    async with Client(Recorder(), settings(hsts_enabled=True, hsts_max_age_seconds=600)) as client:
        response = await client.get("/api/catalog/products")
    assert response.headers["strict-transport-security"] == "max-age=600; includeSubDomains"


async def test_streaming_responses_are_hardened_too() -> None:
    stream = httpx.Response(
        200, content=b"event: done\ndata: {}\n\n", headers={"content-type": "text/event-stream"}
    )
    async with Client(Recorder(stream), settings()) as client:
        response = await client.post("/api/assistant/chat/stream", json={"message": "oi"})
    assert_hardened(response)


async def test_a_body_over_the_limit_is_refused_before_reaching_the_upstream() -> None:
    recorder = Recorder()
    async with Client(recorder, settings(max_request_body_bytes=1000)) as client:
        response = await client.post(
            "/api/orders", content=b"x" * 1001, headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 413
    assert response.json()["detail"] == "request body too large"
    assert response.headers["x-request-id"]
    assert_hardened(response)
    assert recorder.requests == []


async def test_a_body_at_the_limit_goes_through() -> None:
    recorder = Recorder()
    async with Client(recorder, settings(max_request_body_bytes=1000)) as client:
        response = await client.post("/api/orders", content=b"x" * 1000)
    assert response.status_code == 200
    assert len(recorder.requests[0].content) == 1000


async def test_a_chunked_body_without_a_length_is_cut_when_it_exceeds_the_limit() -> None:
    recorder = Recorder()

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(20):
            yield b"y" * 100

    async with Client(recorder, settings(max_request_body_bytes=1000)) as client:
        response = await client.post("/api/orders", content=chunks())
    assert response.status_code == 413
    assert recorder.requests == []


async def test_the_413_carries_cors_headers_so_the_browser_can_read_it() -> None:
    async with Client(Recorder(), settings(max_request_body_bytes=10)) as client:
        response = await client.post(
            "/api/orders", content=b"z" * 50, headers={"Origin": "http://localhost:5173"}
        )
    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.parametrize("method", ["GET", "HEAD"])
async def test_requests_without_a_body_are_not_affected(method: str) -> None:
    async with Client(Recorder(), settings(max_request_body_bytes=1)) as client:
        response = await client.request(method, "/api/catalog/products")
    assert response.status_code == 200


async def test_the_default_limit_is_one_mebibyte() -> None:
    assert settings().max_request_body_bytes == 1_048_576
