from __future__ import annotations

import asyncio
import math
import random
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from marketplace_common.observability import get_request_id
from marketplace_common.resilience import (
    BulkheadFullError,
    CircuitOpenError,
    Deadline,
    DeadlineExceeded,
    current_deadline,
    deadline_event_hooks,
    deadline_scope,
    install_deadline,
)
from marketplace_common.resilience.clock import Sleeper, sleep
from marketplace_common.security import strip_identity_headers
from marketplace_common.security.revocation import RevocationChecker
from starlette.background import BackgroundTask

from gateway.auth import Denied, GatewayAuth, JwksCache, TokenVerifier
from gateway.auth.guard import Revocations
from gateway.client_ip import ClientIpResolver
from gateway.config import Settings
from gateway.rate_limit import Limiter, build_limiter, build_redis
from gateway.routes import resolve
from gateway.upstream import UpstreamGuard

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
PAYMENT_PENDING_RETRY_SECONDS = 1
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]


def _request_id(request: Request) -> str:
    current = get_request_id()
    if current:
        return current
    incoming = request.headers.get("x-request-id", "")
    return incoming if 0 < len(incoming) <= 64 and incoming.isprintable() else uuid.uuid4().hex


def _json(
    status: int,
    detail: str,
    request_id: str,
    headers: dict[str, str] | None = None,
    extra: dict[str, object] | None = None,
) -> Response:
    response = JSONResponse(
        {"detail": detail, **(extra or {})}, status_code=status, headers=headers
    )
    response.headers["X-Request-Id"] = request_id
    return response


def _unavailable(
    request_id: str, service: str, code: str, retry_after: float, headers: dict[str, str]
) -> Response:
    seconds = max(1, math.ceil(retry_after))
    return _json(
        503,
        f"{service} is temporarily unavailable",
        request_id,
        {**headers, "Retry-After": str(seconds)},
        {"code": code, "service": service, "retry_after_seconds": seconds},
    )


def _service_deadline_factory(settings: Settings) -> Callable[[Request, str], Deadline | None]:
    def resolve_deadline(request: Request, service: str) -> Deadline | None:
        current = current_deadline()
        override = settings.service_deadlines.get(service)
        if override is None or "x-request-deadline" in request.headers:
            return current
        return Deadline.after(min(override, settings.max_request_deadline_seconds))

    return resolve_deadline


def _build_auth(
    settings: Settings, client: httpx.AsyncClient, revocations: Revocations | None
) -> GatewayAuth | None:
    if not settings.auth_enabled:
        return None
    jwks = JwksCache(f"{settings.identity_url}/.well-known/jwks.json", client)
    verifier = TokenVerifier(jwks, settings.jwt_issuer, settings.jwt_audience)
    return GatewayAuth(
        verifier,
        settings.internal_auth_secret,
        guest_checkout=settings.allow_guest_checkout,
        ordering_url=settings.ordering_url,
        revocations=revocations,
    )


def create_app(
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    rate_limiter: Limiter | None = None,
    sleeper: Sleeper = sleep,
    rng: random.Random | None = None,
    revocations: Revocations | None = None,
) -> FastAPI:
    settings = settings or Settings()
    upstreams = settings.upstreams()
    redis = None if rate_limiter is not None else build_redis(settings)
    limiter: Limiter = rate_limiter or build_limiter(settings, redis)
    _service_deadline = _service_deadline_factory(settings)
    if revocations is None and redis is not None:
        revocations = RevocationChecker(
            redis,
            cache_seconds=settings.revocation_cache_seconds,
            fail_open=settings.revocation_fail_open,
        )
    guard = UpstreamGuard(settings, list(upstreams), sleeper=sleeper, rng=rng)
    client_ips = ClientIpResolver(settings.trusted_proxies)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.client = httpx.AsyncClient(
            timeout=settings.upstream_timeout,
            transport=transport,
            event_hooks=deadline_event_hooks(),
        )
        app.state.auth = _build_auth(settings, app.state.client, revocations)
        yield
        await app.state.client.aclose()
        if redis is not None:
            await redis.aclose()

    app = FastAPI(title="gateway", lifespan=lifespan)
    app.state.guard = guard
    install_deadline(
        app,
        default_seconds=settings.request_deadline_seconds,
        max_seconds=settings.max_request_deadline_seconds,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=METHODS,
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "If-None-Match",
            "X-Request-Id",
            "X-Request-Deadline",
        ],
        expose_headers=[
            "Idempotent-Replayed",
            "X-Request-Id",
            "ETag",
            "Retry-After",
            "RateLimit-Limit",
            "RateLimit-Remaining",
            "RateLimit-Reset",
        ],
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
        healthy = all(v == "ok" for v in services.values()) and guard.all_closed()
        return JSONResponse(
            {
                "status": "ok" if healthy else "degraded",
                "services": services,
                "breakers": guard.snapshot(),
            },
            status_code=200 if healthy else 503,
        )

    @app.api_route("/api/{path:path}", methods=METHODS)
    async def proxy(request: Request) -> Response:
        request_id = _request_id(request)
        client_ip = client_ips.resolve(
            request.client.host if request.client else None,
            request.headers.get("x-forwarded-for"),
            request.headers.get("x-real-ip"),
        )
        target = resolve(request.url.path)
        decision = await limiter.acquire(target.service if target else "unmatched", client_ip)
        rate_headers = decision.headers()
        if not decision.allowed:
            return _json(429, "too many requests", request_id, rate_headers)

        if target is None or (target.dev_only and not settings.enable_dev_routes):
            return _json(404, "not found", request_id, rate_headers)

        client: httpx.AsyncClient = request.app.state.client
        auth: GatewayAuth | None = request.app.state.auth
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
        headers = strip_identity_headers(headers)
        headers.pop("x-real-ip", None)
        headers["x-forwarded-for"] = client_ip
        query = request.url.query
        order_confirmed = False
        if auth is not None:
            verdict = await auth.authorize(request, client, request_id)
            if isinstance(verdict, Denied):
                challenge = {"WWW-Authenticate": "Bearer"} if verdict.challenge else None
                return _json(verdict.status, verdict.detail, request_id, challenge)
            query = verdict.query
            order_confirmed = verdict.order_confirmed
            headers = auth.upstream_headers(headers, verdict.principal, request_id)
        headers["x-request-id"] = request_id
        upstream_request = client.build_request(
            request.method,
            upstreams[target.service] + target.path,
            params=query,
            content=await request.body(),
            headers=headers,
        )
        try:
            with deadline_scope(_service_deadline(request, target.service)):
                upstream = await guard.send(client, target.service, upstream_request)
        except CircuitOpenError as error:
            return _unavailable(
                request_id, target.service, "circuit_open", error.retry_after_seconds, rate_headers
            )
        except BulkheadFullError as error:
            return _unavailable(
                request_id, target.service, "overloaded", error.retry_after_seconds, rate_headers
            )
        except DeadlineExceeded:
            return _json(504, "request deadline exceeded", request_id, rate_headers)
        except httpx.TimeoutException:
            return _json(504, "upstream timeout", request_id, rate_headers)
        except httpx.HTTPError:
            return _json(502, "upstream unavailable", request_id, rate_headers)

        if upstream.headers.get("content-type", "").startswith("text/event-stream"):
            streaming = StreamingResponse(
                upstream.aiter_bytes(),
                status_code=upstream.status_code,
                headers={
                    k: v for k, v in upstream.headers.items() if k.lower() not in RESPONSE_DROP
                },
                background=BackgroundTask(upstream.aclose),
            )
            streaming.headers["X-Request-Id"] = request_id
            streaming.headers["X-Accel-Buffering"] = "no"
            for key, value in rate_headers.items():
                streaming.headers[key] = value
            return streaming

        if order_confirmed and upstream.status_code == 404:
            return _json(
                202,
                "payment is being created",
                request_id,
                {**rate_headers, "Retry-After": str(PAYMENT_PENDING_RETRY_SECONDS)},
                {"retry_after_seconds": PAYMENT_PENDING_RETRY_SECONDS},
            )

        response = Response(content=upstream.content, status_code=upstream.status_code)
        for key, value in upstream.headers.multi_items():
            if key.lower() not in RESPONSE_DROP:
                response.headers.append(key, value)
        response.headers["X-Request-Id"] = request_id
        for key, value in rate_headers.items():
            response.headers[key] = value
        return response

    return app
