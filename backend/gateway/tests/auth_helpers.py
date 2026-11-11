from __future__ import annotations

import base64
import time
from typing import Any
from uuid import UUID, uuid4

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from marketplace_common.security import scopes_for_roles

from gateway.app import create_app
from gateway.config import Settings

ISSUER = "marketplace-identity"
AUDIENCE = "marketplace-api"
SECRET = "test-secret"


class Issuer:
    def __init__(self, kid: str = "key-1") -> None:
        self.kid = kid
        self.private_key = Ed25519PrivateKey.generate()

    def jwk(self) -> dict[str, Any]:
        raw = self.private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        x = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
        return {"kty": "OKP", "crv": "Ed25519", "x": x, "kid": self.kid, "use": "sig"}

    def token(
        self,
        roles: tuple[str, ...] = ("customer",),
        user_id: UUID | None = None,
        merchant_id: UUID | None = None,
        **overrides: Any,
    ) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": str(user_id or uuid4()),
            "jti": uuid4().hex,
            "iat": now,
            "nbf": now,
            "exp": now + 600,
            "roles": list(roles),
            "scope": " ".join(sorted(scopes_for_roles(frozenset(roles)))),
        }
        if merchant_id:
            claims["merchant_id"] = str(merchant_id)
        claims.update(overrides)
        return jwt.encode(
            claims, self.private_key, algorithm="EdDSA", headers={"kid": self.kid, "typ": "at+jwt"}
        )


class World:
    """Upstreams falsos: serve o JWKS do identity e grava o que chega nos demais serviços."""

    def __init__(self, issuer: Issuer) -> None:
        self.issuer = issuer
        self.requests: list[httpx.Request] = []
        self.jwks_hits = 0
        self.jwks_down = False
        self.order_status = 200
        self.payment_status = 200
        self.extra_keys: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "identity" and request.url.path == "/.well-known/jwks.json":
            self.jwks_hits += 1
            if self.jwks_down:
                return httpx.Response(503)
            return httpx.Response(200, json={"keys": [self.issuer.jwk(), *self.extra_keys]})
        self.requests.append(request)
        if (
            request.url.host == "ordering"
            and request.method == "GET"
            and "/orders/" in request.url.path
        ):
            return httpx.Response(self.order_status, json={"id": "x"})
        if request.url.host == "payments":
            if self.payment_status == 404:
                return httpx.Response(404, json={"detail": "payment not found"})
            return httpx.Response(self.payment_status, json={"ok": True})
        return httpx.Response(200, json={"ok": True})

    def upstream(self, host: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host == host]


async def call(
    world: World, method: str, url: str, settings: Settings, **kwargs: Any
) -> httpx.Response:
    app = create_app(settings, transport=httpx.MockTransport(world))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gw") as client:
            return await client.request(method, url, **kwargs)
