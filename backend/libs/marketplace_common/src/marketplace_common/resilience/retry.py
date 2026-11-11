from __future__ import annotations

import asyncio
import random
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from marketplace_common.resilience import metrics
from marketplace_common.resilience.clock import Clock, Sleeper, monotonic, sleep
from marketplace_common.resilience.deadline import current_deadline
from marketplace_common.resilience.errors import (
    BulkheadFullError,
    CircuitOpenError,
    DeadlineExceeded,
)

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
SAFE_RETRY_METHODS = frozenset({"GET", "HEAD"})
NEVER_RETRY = (CircuitOpenError, BulkheadFullError, DeadlineExceeded, asyncio.CancelledError)


def is_idempotent_method(method: str, *, strict: bool = True) -> bool:
    """`strict` aceita só leituras (GET/HEAD); sem ele aceita também PUT e DELETE."""
    return method.upper() in (SAFE_RETRY_METHODS if strict else IDEMPOTENT_METHODS)


class RetryBudget:
    """Limita as retentativas a uma fração do tráfego (mais um piso), para não amplificar uma falha.

    Por janela de `window_seconds`: retentativas permitidas = `min_retries` + `ratio` * requisições.
    """

    def __init__(
        self,
        ratio: float = 0.2,
        min_retries: int = 3,
        window_seconds: float = 10.0,
        clock: Clock = monotonic,
    ) -> None:
        if ratio < 0 or min_retries < 0 or window_seconds <= 0:
            raise ValueError("invalid retry budget")
        self._ratio = ratio
        self._min = min_retries
        self._window = window_seconds
        self._clock = clock
        self._requests: deque[float] = deque()
        self._retries: deque[float] = deque()

    def _trim(self) -> None:
        horizon = self._clock() - self._window
        for events in (self._requests, self._retries):
            while events and events[0] <= horizon:
                events.popleft()

    def record_request(self) -> None:
        self._requests.append(self._clock())

    def try_acquire(self) -> bool:
        self._trim()
        allowed = self._min + self._ratio * len(self._requests)
        if len(self._retries) + 1 > allowed:
            return False
        self._retries.append(self._clock())
        return True

    @property
    def retries_in_window(self) -> int:
        self._trim()
        return len(self._retries)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.1
    max_delay: float = 2.0
    multiplier: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1 or self.base_delay < 0 or self.max_delay < self.base_delay:
            raise ValueError("invalid retry policy")

    def ceiling(self, attempt: int) -> float:
        return min(self.max_delay, self.base_delay * self.multiplier ** (attempt - 1))


def full_jitter(policy: RetryPolicy, attempt: int, rng: random.Random) -> float:
    return rng.uniform(0.0, policy.ceiling(attempt))


def _default_transient(error: BaseException) -> bool:
    return isinstance(error, TimeoutError | ConnectionError | OSError)


async def retry_async[T](
    operation: Callable[[], Awaitable[T]],
    *,
    name: str,
    policy: RetryPolicy | None = None,
    idempotent: bool,
    retry_on: Callable[[BaseException], bool] = _default_transient,
    retry_on_result: Callable[[T], bool] | None = None,
    budget: RetryBudget | None = None,
    rng: random.Random | None = None,
    sleeper: Sleeper = sleep,
) -> T:
    """Executa `operation` com retentativas (backoff exponencial com full jitter).

    Só retenta se `idempotent=True` e o erro for transitório (`retry_on`). Nunca retenta circuito
    aberto, bulkhead cheio ou deadline estourado; respeita o orçamento e o tempo que sobrou.
    """
    policy = policy or RetryPolicy()
    attempts = policy.max_attempts if idempotent else 1
    generator = rng or random.Random()
    if budget is not None:
        budget.record_request()
    last_result: T | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = await operation()
        except NEVER_RETRY:
            raise
        except BaseException as error:
            if not idempotent or not retry_on(error):
                metrics.RETRY_EVENTS.labels(name, "not_retryable").inc()
                raise
            if attempt >= attempts:
                metrics.RETRY_EVENTS.labels(name, "exhausted").inc()
                raise
            if not await _wait_for_next(name, policy, attempt, budget, generator, sleeper):
                raise
            continue
        if retry_on_result is None or not retry_on_result(result):
            return result
        last_result = result
        if attempt >= attempts:
            metrics.RETRY_EVENTS.labels(name, "exhausted").inc()
            return result
        if not await _wait_for_next(name, policy, attempt, budget, generator, sleeper):
            return result
    assert last_result is not None
    return last_result


async def _wait_for_next(
    name: str,
    policy: RetryPolicy,
    attempt: int,
    budget: RetryBudget | None,
    rng: random.Random,
    sleeper: Sleeper,
) -> bool:
    delay = full_jitter(policy, attempt, rng)
    deadline = current_deadline()
    if deadline is not None and deadline.remaining() <= delay:
        metrics.RETRY_EVENTS.labels(name, "deadline").inc()
        return False
    if budget is not None and not budget.try_acquire():
        metrics.RETRY_EVENTS.labels(name, "budget_denied").inc()
        return False
    metrics.RETRY_EVENTS.labels(name, "retried").inc()
    await sleeper(delay)
    return True
