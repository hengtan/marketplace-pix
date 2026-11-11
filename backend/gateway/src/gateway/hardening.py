from __future__ import annotations

import uuid

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

Headers = dict[str, str]

DEFAULT_SECURITY_HEADERS: Headers = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Resource-Policy": "same-site",
}

BODY_TOO_LARGE = "request body too large"


class BodyTooLarge(Exception):
    pass


def _request_id(scope: Scope) -> str:
    for name, value in scope.get("headers", []):
        if name == b"x-request-id":
            text = value.decode("latin-1")
            if 0 < len(text) <= 64 and text.isprintable():
                return str(text)
    return uuid.uuid4().hex


class SecurityHeadersMiddleware:
    """Cabeçalhos de segurança em toda resposta do gateway, inclusive as geradas por ele. O que o
    upstream mandar com o mesmo nome é sobrescrito: a política é do gateway."""

    def __init__(self, app: ASGIApp, headers: Headers) -> None:
        self.app = app
        self._headers = {name.lower().encode(): value.encode() for name, value in headers.items()}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def hardened(message: Message) -> None:
            if message["type"] == "http.response.start":
                kept = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() not in self._headers
                ]
                message = {**message, "headers": [*kept, *self._headers.items()]}
            await send(message)

        await self.app(scope, receive, hardened)


class BodyLimitMiddleware:
    """Recusa com 413 o corpo acima do limite: pelo `Content-Length`, sem ler nada, ou, quando o
    corpo vem em pedaços sem tamanho declarado, no momento em que a soma passa do limite."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self._max = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self._max <= 0:
            await self.app(scope, receive, send)
            return
        declared = _content_length(scope)
        if declared is not None and declared > self._max:
            await self._refuse(scope, receive, send)
            return

        seen = 0
        started = False

        async def counting() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self._max:
                    raise BodyTooLarge
            return message

        async def tracking(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counting, tracking)
        except BodyTooLarge:
            if started:
                raise
            await self._refuse(scope, receive, send)

    async def _refuse(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            {"detail": BODY_TOO_LARGE},
            status_code=413,
            headers={"X-Request-Id": _request_id(scope), "Connection": "close"},
        )
        await response(scope, receive, send)


def _content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


def security_headers(hsts_enabled: bool, hsts_max_age_seconds: int, cors_policy: str) -> Headers:
    headers = dict(DEFAULT_SECURITY_HEADERS)
    headers["Cross-Origin-Resource-Policy"] = cors_policy
    if hsts_enabled:
        headers["Strict-Transport-Security"] = f"max-age={hsts_max_age_seconds}; includeSubDomains"
    return headers


__all__ = [
    "BODY_TOO_LARGE",
    "BodyLimitMiddleware",
    "BodyTooLarge",
    "SecurityHeadersMiddleware",
    "security_headers",
]
