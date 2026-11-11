from __future__ import annotations

import logging
import math
from collections.abc import Awaitable
from typing import Protocol

from marketplace_common.resilience.clock import Clock, monotonic

logger = logging.getLogger(__name__)

DEFAULT_PREFIX = "auth:revoked:"


class RevocationUnavailable(Exception):
    """O Redis das revogações não respondeu e o modo é fail-closed."""


class RevocationWriteRedis(Protocol):
    def set(self, name: str, value: str, ex: int | None = None) -> Awaitable[object]: ...


class RevocationReadRedis(Protocol):
    def exists(self, *names: str) -> Awaitable[int]: ...


class RedisAccessTokenRevocations:
    """Lista de `jti` revogados. A chave vive exatamente o que resta de vida ao token, então a
    lista não cresce além dos tokens ainda válidos."""

    def __init__(self, redis: RevocationWriteRedis, prefix: str = DEFAULT_PREFIX) -> None:
        self._redis = redis
        self._prefix = prefix

    async def revoke(self, jti: str, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        await self._redis.set(f"{self._prefix}{jti}", "1", ex=math.ceil(ttl_seconds))


class RevocationChecker:
    """Consulta a lista com um cache curto (`cache_seconds`): uma revogação vale para o gateway
    em no máximo esse tempo. Revogado nunca volta atrás, então o `sim` fica guardado. Com o Redis
    fora, `fail_open` decide: aceita o token (disponibilidade; o token ainda expira sozinho) ou
    recusa. Depois de uma falha o Redis fica de lado por `retry_after` segundos."""

    def __init__(
        self,
        redis: RevocationReadRedis,
        *,
        prefix: str = DEFAULT_PREFIX,
        cache_seconds: float = 0.5,
        fail_open: bool = True,
        retry_after: float = 2.0,
        max_entries: int = 10_000,
        clock: Clock = monotonic,
    ) -> None:
        self._redis = redis
        self._prefix = prefix
        self._cache_seconds = cache_seconds
        self._fail_open = fail_open
        self._retry_after = retry_after
        self._max_entries = max_entries
        self._clock = clock
        self._revoked: set[str] = set()
        self._clean_until: dict[str, float] = {}
        self._down_until = 0.0

    @property
    def cached_entries(self) -> int:
        return len(self._revoked) + len(self._clean_until)

    async def is_revoked(self, jti: str) -> bool:
        if jti in self._revoked:
            return True
        now = self._clock()
        if self._clean_until.get(jti, 0.0) > now:
            return False
        if now < self._down_until:
            return self._unavailable()
        try:
            revoked = bool(await self._redis.exists(f"{self._prefix}{jti}"))
        except Exception:
            self._down_until = now + self._retry_after
            logger.exception("token revocation lookup failed")
            return self._unavailable()
        self._remember(jti, revoked, now)
        return revoked

    def _unavailable(self) -> bool:
        if self._fail_open:
            return False
        raise RevocationUnavailable

    def _remember(self, jti: str, revoked: bool, now: float) -> None:
        if revoked:
            if len(self._revoked) >= self._max_entries:
                self._revoked.clear()
            self._revoked.add(jti)
            return
        if self._cache_seconds <= 0:
            return
        if len(self._clean_until) >= self._max_entries:
            self._clean_until = {k: v for k, v in self._clean_until.items() if v > now}
            if len(self._clean_until) >= self._max_entries:
                self._clean_until.clear()
        self._clean_until[jti] = now + self._cache_seconds
