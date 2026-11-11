from __future__ import annotations

import asyncio
import math
import random
from collections.abc import Awaitable, Callable
from datetime import datetime

from marketplace_common.resilience import (
    BreakerConfig,
    Bulkhead,
    CircuitBreaker,
    ResilienceError,
    RetryBudget,
    RetryPolicy,
    cap_timeout,
    retry_async,
)
from marketplace_common.resilience.clock import Sleeper, sleep
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

from payments.application.errors import PspUnavailable
from payments.application.ports import ChargeStatus, PspCharge, PspGateway
from payments.domain.money import Money

TRANSIENT = (TimeoutError, ConnectionError, OSError, OperationalError, InterfaceError)


def _is_transient(error: BaseException) -> bool:
    if isinstance(error, DBAPIError) and error.connection_invalidated:
        return True
    return isinstance(error, TRANSIENT)


class ResilientPsp:
    """Decora o PSP com timeout (limitado pelo deadline), retry, circuit breaker e bulkhead.

    As três operações do PSP são idempotentes (cobrança por referência, leitura de status e
    cancelamento), então todas podem ser retentadas. Qualquer falha vira `PspUnavailable`, que a
    API traduz em 503 + Retry-After para o PSP reenviar o webhook mais tarde.
    """

    def __init__(
        self,
        inner: PspGateway,
        *,
        timeout: float = 2.0,
        breaker: CircuitBreaker | None = None,
        bulkhead: Bulkhead | None = None,
        retry_policy: RetryPolicy | None = None,
        budget: RetryBudget | None = None,
        neutral_errors: tuple[type[Exception], ...] = (),
        sleeper: Sleeper = sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._inner = inner
        self._timeout = timeout
        self._neutral = neutral_errors
        self._breaker = breaker or CircuitBreaker(
            "psp",
            BreakerConfig(minimum_calls=5, window_size=10, open_seconds=15.0),
            is_failure=lambda e: not isinstance(e, (ResilienceError, *neutral_errors)),
        )
        self._bulkhead = bulkhead or Bulkhead("psp", max_concurrent=20, max_queue=20)
        self._policy = retry_policy or RetryPolicy(max_attempts=3, base_delay=0.05, max_delay=0.5)
        self._budget = budget or RetryBudget()
        self._sleeper = sleeper
        self._rng = rng

    @property
    def breaker(self) -> CircuitBreaker:
        return self._breaker

    async def _call[T](self, operation: str, call: Callable[[], Awaitable[T]]) -> T:
        async def attempt() -> T:
            async def guarded() -> T:
                async with self._bulkhead.slot():
                    async with asyncio.timeout(cap_timeout(self._timeout)):
                        return await call()

            return await self._breaker.call(guarded)

        def retryable(error: BaseException) -> bool:
            return _is_transient(error) and not isinstance(error, self._neutral)

        try:
            return await retry_async(
                attempt,
                name=f"psp-{operation}",
                idempotent=True,
                policy=self._policy,
                retry_on=retryable,
                budget=self._budget,
                rng=self._rng,
                sleeper=self._sleeper,
            )
        except ResilienceError as error:
            raise PspUnavailable(
                f"psp unavailable: {error}", math.ceil(max(error.retry_after_seconds, 1.0))
            ) from error
        except self._neutral:
            raise
        except Exception as error:
            raise PspUnavailable(f"psp call failed: {type(error).__name__}") from error

    async def create_charge(self, reference: str, amount: Money, expires_at: datetime) -> PspCharge:
        return await self._call(
            "create_charge", lambda: self._inner.create_charge(reference, amount, expires_at)
        )

    async def get_charge_status(self, charge_id: str) -> ChargeStatus:
        return await self._call(
            "get_charge_status", lambda: self._inner.get_charge_status(charge_id)
        )

    async def cancel_charge(self, charge_id: str) -> bool:
        return await self._call("cancel_charge", lambda: self._inner.cancel_charge(charge_id))
