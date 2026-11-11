from __future__ import annotations

import contextvars
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from marketplace_common.resilience import metrics
from marketplace_common.resilience.clock import Clock, monotonic
from marketplace_common.resilience.errors import DeadlineExceeded

logger = logging.getLogger(__name__)

DEADLINE_HEADER = "X-Request-Deadline"
_DEADLINE_HEADER_BYTES = DEADLINE_HEADER.lower().encode()


class Deadline:
    """Orçamento de tempo de uma requisição. No header trafega o tempo restante em milissegundos.

    O valor é relativo (como o grpc-timeout) para não depender de relógios sincronizados entre os
    serviços: cada salto converte para um instante absoluto no seu relógio monotônico.
    """

    __slots__ = ("_at", "_clock")

    def __init__(self, expires_at: float, clock: Clock = monotonic) -> None:
        self._at = expires_at
        self._clock = clock

    @classmethod
    def after(cls, seconds: float, clock: Clock = monotonic) -> Deadline:
        return cls(clock() + seconds, clock)

    @classmethod
    def parse(cls, value: str | None, clock: Clock = monotonic) -> Deadline | None:
        if value is None:
            return None
        try:
            millis = float(value.strip())
        except ValueError:
            return None
        if millis != millis or millis in (float("inf"), float("-inf")):
            return None
        return cls.after(max(millis, 0.0) / 1000.0, clock)

    def remaining(self) -> float:
        return max(0.0, self._at - self._clock())

    @property
    def expired(self) -> bool:
        return self._clock() >= self._at

    def check(self, where: str = "unknown") -> None:
        if self.expired:
            metrics.DEADLINE_EXCEEDED.labels(where).inc()
            raise DeadlineExceeded

    def timeout(self, cap: float | None = None, reserve: float = 0.0) -> float:
        """Tempo que sobrou menos uma reserva, limitado por `cap`."""
        left = max(0.0, self.remaining() - reserve)
        return left if cap is None else min(left, cap)

    def header_value(self, reserve: float = 0.0) -> str:
        return str(int(max(0.0, self.remaining() - reserve) * 1000))

    def tighten(self, seconds: float) -> Deadline:
        return Deadline(min(self._at, self._clock() + seconds), self._clock)


_current: contextvars.ContextVar[Deadline | None] = contextvars.ContextVar(
    "request_deadline", default=None
)


def current_deadline() -> Deadline | None:
    return _current.get()


def set_deadline(deadline: Deadline | None) -> contextvars.Token[Deadline | None]:
    return _current.set(deadline)


@contextmanager
def deadline_scope(deadline: Deadline | None) -> Iterator[Deadline | None]:
    token = _current.set(deadline)
    try:
        yield deadline
    finally:
        _current.reset(token)


def cap_timeout(default: float, reserve: float = 0.0) -> float:
    deadline = _current.get()
    return default if deadline is None else deadline.timeout(default, reserve)


def check_deadline(where: str = "unknown") -> None:
    deadline = _current.get()
    if deadline is not None:
        deadline.check(where)


def outbound_headers(reserve: float = 0.0) -> dict[str, str]:
    deadline = _current.get()
    return {} if deadline is None else {DEADLINE_HEADER: deadline.header_value(reserve)}


async def _propagate_deadline(request: httpx.Request) -> None:
    deadline = _current.get()
    if deadline is None:
        return
    deadline.check("http_client")
    request.headers[DEADLINE_HEADER] = deadline.header_value()
    timeout: Mapping[str, Any] = request.extensions.get("timeout", {})
    left = deadline.remaining()
    request.extensions["timeout"] = {
        key: (left if value is None else min(float(value), left)) for key, value in timeout.items()
    } or {"connect": left, "read": left, "write": left, "pool": left}


def deadline_event_hooks() -> dict[str, list[Any]]:
    """Para `httpx.AsyncClient(event_hooks=...)`: repassa o header e limita os timeouts."""
    return {"request": [_propagate_deadline]}


class DeadlineMiddleware:
    """Lê X-Request-Deadline (ou aplica o padrão), limita ao teto e responde 504 se já estourou."""

    def __init__(
        self,
        app: ASGIApp,
        default_seconds: float | None = None,
        max_seconds: float | None = None,
        clock: Clock = monotonic,
    ) -> None:
        self.app = app
        self._default = default_seconds
        self._max = max_seconds
        self._clock = clock

    def _resolve(self, scope: Scope) -> Deadline | None:
        raw = dict(scope["headers"]).get(_DEADLINE_HEADER_BYTES)
        deadline = Deadline.parse(raw.decode("latin-1") if raw else None, self._clock)
        if deadline is None and self._default is not None:
            deadline = Deadline.after(self._default, self._clock)
        if deadline is not None and self._max is not None:
            deadline = deadline.tighten(self._max)
        return deadline

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        deadline = self._resolve(scope)
        if deadline is not None and deadline.expired:
            metrics.DEADLINE_EXCEEDED.labels("ingress").inc()
            response = JSONResponse({"detail": "request deadline exceeded"}, status_code=504)
            await response(scope, receive, send)
            return
        token = _current.set(deadline)

        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)


def install_deadline(
    app: FastAPI, default_seconds: float | None = None, max_seconds: float | None = None
) -> None:
    app.add_middleware(DeadlineMiddleware, default_seconds=default_seconds, max_seconds=max_seconds)

    @app.exception_handler(DeadlineExceeded)
    async def deadline_exceeded(_: Request, exc: DeadlineExceeded) -> JSONResponse:
        return JSONResponse({"detail": "request deadline exceeded"}, status_code=504)
