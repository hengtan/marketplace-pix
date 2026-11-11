from __future__ import annotations

import json
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, aclosing
from typing import Any
from uuid import UUID

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from assistant.application.budget import BudgetExceeded
from assistant.domain.errors import MessageTooLong, SessionNotFound, UpstreamUnavailable
from assistant.interface.schemas import (
    CacheStatsOut,
    ChatRequest,
    ChatResponse,
    EvalRunOut,
    MessageOut,
    ReindexOut,
    SessionOut,
    ToolCallOut,
)
from assistant.metrics import STREAMS_ACTIVE
from assistant.wiring import Container

ReadyCheck = Callable[[], Awaitable[bool]]
Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def _container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


def user_key(request: Request) -> str | None:
    header = request.headers.get("x-user-id", "").strip()
    if header:
        return f"user:{header[:64]}"
    client = request.client.host if request.client else None
    return f"ip:{client}" if client else None


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def build_router() -> APIRouter:
    router = APIRouter()

    @router.post("/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest, request: Request) -> ChatResponse:
        result = await _container(request).chat.chat(
            body.session_id, body.message, user_key(request)
        )
        return ChatResponse.from_result(result)

    @router.post("/chat/stream")
    async def chat_stream(body: ChatRequest, request: Request) -> StreamingResponse:
        service = _container(request).chat
        message = service.validate_message(body.message)
        user = user_key(request)

        async def events() -> AsyncIterator[str]:
            STREAMS_ACTIVE.inc()
            try:
                async with aclosing(
                    service.stream(body.session_id, message, user_id=user)
                ) as stream:
                    async for event in stream:
                        if await request.is_disconnected():
                            return
                        if event.kind == "tool_call":
                            yield _sse(
                                "tool_call", ToolCallOut.from_domain(event.payload).model_dump()
                            )
                        elif event.kind == "token":
                            yield _sse("token", {"text": event.payload})
                        elif event.kind == "warning":
                            yield _sse("warning", event.payload)
                        else:
                            done = ChatResponse.from_result(event.payload)
                            yield _sse("done", json.loads(done.model_dump_json()))
            except UpstreamUnavailable:
                yield _sse("error", {"detail": "model unavailable"})
            except BudgetExceeded as exc:
                yield _sse("error", {"detail": "budget exceeded", "scope": exc.scope})
            finally:
                STREAMS_ACTIVE.dec()

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/sessions/{session_id}", response_model=SessionOut)
    async def get_session(session_id: UUID, request: Request) -> SessionOut:
        created, messages = await _container(request).chat.get_session(session_id)
        return SessionOut(
            session_id=session_id,
            created_at=created,
            messages=[MessageOut.from_stored(m) for m in messages],
        )

    @router.post("/admin/reindex", response_model=ReindexOut)
    async def reindex(request: Request) -> ReindexOut:
        report = await _container(request).ingest.execute()
        return ReindexOut(**report.to_dict())

    @router.get("/cache/stats", response_model=CacheStatsOut)
    async def cache_stats(request: Request) -> CacheStatsOut:
        cache = _container(request).cache
        summary = await cache.summary()
        stats = cache.stats
        return CacheStatsOut(
            enabled=cache.enabled,
            entries=summary.entries,
            persisted_hits=summary.hits,
            persisted_tokens_saved=summary.tokens_saved,
            lookups=stats.lookups,
            hits=stats.hits,
            misses=stats.misses,
            skips=stats.skips,
            hit_rate=stats.hit_rate,
            tokens_saved=stats.tokens_saved,
            cost_saved_usd=round(stats.cost_saved_usd, 6),
        )

    @router.get("/evals/latest", response_model=EvalRunOut)
    async def latest_eval(request: Request) -> EvalRunOut | JSONResponse:
        record = await _container(request).eval_store.latest()
        if record is None:
            return JSONResponse({"detail": "no eval run yet"}, status_code=404)
        return EvalRunOut.from_record(record)

    @router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/ready")
    async def ready(request: Request) -> JSONResponse:
        check: ReadyCheck | None = getattr(request.app.state, "ready_check", None)
        ok = True if check is None else await check()
        return JSONResponse({"ready": ok}, status_code=200 if ok else 503)

    return router


def create_app(
    *,
    container: Container | None = None,
    ready_check: ReadyCheck | None = None,
    lifespan: Lifespan | None = None,
) -> FastAPI:
    app = FastAPI(title="assistant", lifespan=lifespan)
    if container is not None:
        app.state.container = container
    if ready_check is not None:
        app.state.ready_check = ready_check
    app.include_router(build_router())

    @app.exception_handler(SessionNotFound)
    async def session_not_found(_: Request, exc: SessionNotFound) -> JSONResponse:
        return JSONResponse({"detail": "session not found"}, status_code=404)

    @app.exception_handler(MessageTooLong)
    async def too_long(_: Request, exc: MessageTooLong) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(BudgetExceeded)
    async def over_budget(_: Request, exc: BudgetExceeded) -> JSONResponse:
        return JSONResponse(
            {"detail": "budget exceeded", "scope": exc.scope, "limit": exc.limit},
            status_code=429,
            headers={"Retry-After": "3600"},
        )

    @app.exception_handler(UpstreamUnavailable)
    async def upstream(_: Request, exc: UpstreamUnavailable) -> JSONResponse:
        if exc.retry_after_seconds is None:
            return JSONResponse({"detail": "upstream service unavailable"}, status_code=502)
        return JSONResponse(
            {"detail": "model temporarily unavailable", "code": "model_unavailable"},
            status_code=503,
            headers={"Retry-After": str(max(1, math.ceil(exc.retry_after_seconds)))},
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"] if part != "body")
        return JSONResponse({"detail": f"invalid {location}: {first['msg']}"}, status_code=422)

    return app
