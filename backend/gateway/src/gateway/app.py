from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from gateway.config import Settings
from gateway.rate_limit import RateLimiter
from gateway.routes import resolve

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}
RESPONSE_DROP = HOP_BY_HOP | {"content-encoding"}
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]


def _request_id(request: Request) -> str:
    incoming = request.headers.get("x-request-id", "")
    return incoming if 0 < len(incoming) <= 64 and incoming.isprintable() else uuid.uuid4().hex


def _json(
    status: int, detail: str, request_id: str, headers: dict[str, str] | None = None
) -> Response:
    response = JSONResponse({"detail": detail}, status_code=status, headers=headers)
    response.headers["X-Request-Id"] = request_id
    return response


def create_app(
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    rate_limiter: RateLimiter | None = None,
) -> FastAPI:
    settings = settings or Settings()
    upstreams = settings.upstreams()
    limiter = rate_limiter or RateLimiter(settings.rate_limit_per_minute)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.client = httpx.AsyncClient(timeout=settings.upstream_timeout, transport=transport)
        yield
        await app.state.client.aclose()

    app = FastAPI(title="gateway", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=METHODS,
        allow_headers=["Content-Type", "Idempotency-Key", "If-None-Match", "X-Request-Id"],
        expose_headers=["Idempotent-Replayed", "X-Request-Id", "ETag"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/health")
    async def api_health(request: Request) -> Response:
        client: httpx.AsyncClient = request.app.state.client

        async def probe(base: str) -> str:
            try:
                response = await client.get(f"{base}/health", timeout=2.0)
                return "ok" if response.status_code == 200 else "down"
            except httpx.HTTPError:
                return "down"

        names = list(upstreams)
        results = await asyncio.gather(*(probe(upstreams[n]) for n in names))
        services = dict(zip(names, results, strict=True))
        healthy = all(v == "ok" for v in services.values())
        return JSONResponse(
            {"status": "ok" if healthy else "degraded", "services": services},
            status_code=200 if healthy else 503,
        )

    @app.api_route("/api/{path:path}", methods=METHODS)
    async def proxy(request: Request) -> Response:
        request_id = _request_id(request)
        client_ip = request.client.host if request.client else "unknown"
        retry_after = limiter.check(client_ip)
        if retry_after is not None:
            return _json(
                429, "too many requests", request_id, {"Retry-After": str(int(retry_after) + 1)}
            )

        target = resolve(request.url.path)
        if target is None or (target.dev_only and not settings.enable_dev_routes):
            return _json(404, "not found", request_id)

        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
        headers["x-request-id"] = request_id
        client: httpx.AsyncClient = request.app.state.client
        try:
            upstream = await client.request(
                request.method,
                upstreams[target.service] + target.path,
                params=request.url.query,
                content=await request.body(),
                headers=headers,
            )
        except httpx.TimeoutException:
            return _json(504, "upstream timeout", request_id)
        except httpx.HTTPError:
            return _json(502, "upstream unavailable", request_id)

        response = Response(content=upstream.content, status_code=upstream.status_code)
        for key, value in upstream.headers.multi_items():
            if key.lower() not in RESPONSE_DROP:
                response.headers.append(key, value)
        response.headers["X-Request-Id"] = request_id
        return response

    return app
