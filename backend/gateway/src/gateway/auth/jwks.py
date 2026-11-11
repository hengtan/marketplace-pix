from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import httpx
import jwt


class JwksUnavailable(Exception):
    pass


class JwksCache:
    """Chaves públicas do identity. Recarrega por TTL e quando aparece um `kid` desconhecido."""

    def __init__(
        self,
        url: str,
        client: httpx.AsyncClient,
        ttl_seconds: float = 300.0,
        min_refresh_seconds: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url
        self._client = client
        self._ttl = ttl_seconds
        self._min_refresh = min_refresh_seconds
        self._clock = clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._loaded_at: float | None = None
        self._last_attempt: float | None = None
        self._lock = asyncio.Lock()

    async def get(self, kid: str) -> jwt.PyJWK | None:
        now = self._clock()
        stale = self._loaded_at is None or now - self._loaded_at > self._ttl
        if kid in self._keys and not stale:
            return self._keys[kid]
        async with self._lock:
            now = self._clock()
            stale = self._loaded_at is None or now - self._loaded_at > self._ttl
            if (kid not in self._keys or stale) and self._can_refresh(now):
                await self._refresh(now)
        return self._keys.get(kid)

    def _can_refresh(self, now: float) -> bool:
        return self._last_attempt is None or now - self._last_attempt >= self._min_refresh

    async def _refresh(self, now: float) -> None:
        self._last_attempt = now
        try:
            response = await self._client.get(self._url, timeout=3.0)
            response.raise_for_status()
            document: dict[str, Any] = response.json()
            keys = {
                str(jwk["kid"]): jwt.PyJWK.from_dict(jwk, algorithm="EdDSA")
                for jwk in document["keys"]
            }
        except (httpx.HTTPError, ValueError, KeyError, jwt.PyJWTError) as error:
            if not self._keys:
                raise JwksUnavailable from error
            return
        self._keys = keys
        self._loaded_at = now
