from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from marketplace_common.resilience import RatePolicy, RouteRateLimiter
from marketplace_common.security.backoff import ProgressiveBackoff

from identity.metrics import ABUSE_BLOCKS

logger = logging.getLogger(__name__)

HOUR_SECONDS = 3600.0


class TooManyAttempts(Exception):
    def __init__(self, retry_after: float, reason: str) -> None:
        super().__init__(reason)
        self.retry_after = retry_after
        self.reason = reason


@dataclass(frozen=True, slots=True)
class AbusePolicy:
    login_per_minute_ip_email: int = 10
    login_per_minute_ip: int = 60
    register_per_hour_ip_email: int = 5
    register_per_hour_ip: int = 30
    backoff_base_seconds: float = 2.0
    backoff_max_seconds: float = 900.0

    def default_policy(self) -> RatePolicy:
        return RatePolicy(capacity=0, refill_per_second=0.0)

    def route_policies(self) -> dict[str, RatePolicy]:
        return {
            "login:ip_email": RatePolicy.per_minute(self.login_per_minute_ip_email),
            "login:ip": RatePolicy.per_minute(self.login_per_minute_ip),
            "register:ip_email": _per_hour(self.register_per_hour_ip_email),
            "register:ip": _per_hour(self.register_per_hour_ip),
        }


def _per_hour(limit: int) -> RatePolicy:
    return RatePolicy(limit, limit / HOUR_SECONDS)


def _digest(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]


class AbuseGuard:
    """Protege o cadastro e o login contra enxurrada e adivinhação de senha: limite distribuído por
    IP+e-mail (impede martelar uma conta) e por IP (impede variar o e-mail), mais uma espera que
    dobra a cada falha seguida do mesmo IP+e-mail. O e-mail só entra nas chaves como hash."""

    def __init__(self, limiter: RouteRateLimiter, backoff: ProgressiveBackoff) -> None:
        self._limiter = limiter
        self._backoff = backoff

    def keys_for(self, action: str, ip: str, email: str) -> tuple[str, str]:
        return f"{ip}|{_digest(email)}", ip

    async def check(self, action: str, ip: str, email: str) -> None:
        by_email, by_ip = self.keys_for(action, ip, email)
        wait = await self._backoff.blocked_for(f"{action}:{by_email}")
        if wait > 0:
            ABUSE_BLOCKS.labels(action=action, reason="backoff").inc()
            raise TooManyAttempts(wait, "backoff")
        for route, client in ((f"{action}:ip_email", by_email), (f"{action}:ip", by_ip)):
            decision = await self._limiter.acquire(route, client)
            if not decision.allowed:
                ABUSE_BLOCKS.labels(action=action, reason=route.split(":")[1]).inc()
                raise TooManyAttempts(decision.retry_after, route)

    async def failed(self, action: str, ip: str, email: str) -> float:
        by_email, _ = self.keys_for(action, ip, email)
        return await self._backoff.record_failure(f"{action}:{by_email}")

    async def succeeded(self, action: str, ip: str, email: str) -> None:
        by_email, _ = self.keys_for(action, ip, email)
        await self._backoff.reset(f"{action}:{by_email}")
