from __future__ import annotations

import asyncio
import functools
import logging
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ParamSpec, TypeVar

from marketplace_common.resilience import metrics
from marketplace_common.resilience.clock import Clock, monotonic
from marketplace_common.resilience.errors import CircuitOpenError

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True, slots=True)
class BreakerConfig:
    failure_rate_threshold: float = 0.5
    slow_call_threshold: float | None = None
    slow_call_rate_threshold: float = 0.5
    minimum_calls: int = 10
    window_size: int = 20
    window_seconds: float = 30.0
    open_seconds: float = 10.0
    half_open_max_calls: int = 3
    half_open_retry_after: float = 1.0

    def __post_init__(self) -> None:
        if not 0 < self.failure_rate_threshold <= 1 or not 0 < self.slow_call_rate_threshold <= 1:
            raise ValueError("rate thresholds must be in (0, 1]")
        if self.minimum_calls < 1 or self.window_size < self.minimum_calls:
            raise ValueError("window_size must be >= minimum_calls >= 1")
        if self.half_open_max_calls < 1 or self.open_seconds <= 0 or self.window_seconds <= 0:
            raise ValueError(
                "half_open_max_calls, open_seconds and window_seconds must be positive"
            )


FailurePredicate = Callable[[BaseException], bool]


def _any_exception(_: BaseException) -> bool:
    return True


class _Permit:
    def __init__(self, breaker: CircuitBreaker, probe: bool, started: float) -> None:
        self._breaker = breaker
        self.probe = probe
        self.started = started
        self.failed = False
        self.done = False

    def mark_failure(self) -> None:
        self.failed = True


class CircuitBreaker:
    """Disjuntor com janela deslizante (por contagem e por idade) e sondas limitadas no half-open.

    Roda em um único event loop: as transições não têm `await` no meio, então não há lock.
    """

    def __init__(
        self,
        name: str,
        config: BreakerConfig | None = None,
        *,
        clock: Clock = monotonic,
        is_failure: FailurePredicate = _any_exception,
    ) -> None:
        self.name = name
        self.config = config or BreakerConfig()
        self._clock = clock
        self._is_failure = is_failure
        self._state = BreakerState.CLOSED
        self._window: deque[tuple[float, bool, bool]] = deque()
        self._opened_at = 0.0
        self._probes_in_flight = 0
        self._probes_succeeded = 0
        self._publish_state()

    @property
    def state(self) -> BreakerState:
        self._refresh()
        return self._state

    def snapshot(self) -> dict[str, Any]:
        state = self.state
        calls = len(self._window)
        failures = sum(1 for _, failed, _ in self._window if failed)
        slow = sum(1 for _, _, is_slow in self._window if is_slow)
        return {
            "state": state.value,
            "calls_in_window": calls,
            "failure_rate": round(failures / calls, 3) if calls else 0.0,
            "slow_rate": round(slow / calls, 3) if calls else 0.0,
            "retry_after_seconds": round(self._retry_after(), 3)
            if state is not BreakerState.CLOSED
            else 0.0,
        }

    def reset(self) -> None:
        self._window.clear()
        self._probes_in_flight = 0
        self._probes_succeeded = 0
        self._transition(BreakerState.CLOSED)

    def _retry_after(self) -> float:
        if self._state is BreakerState.OPEN:
            return max(0.0, self._opened_at + self.config.open_seconds - self._clock())
        return self.config.half_open_retry_after

    def _publish_state(self) -> None:
        for state in BreakerState:
            metrics.BREAKER_STATE.labels(self.name, state.value).set(
                1 if state is self._state else 0
            )

    def _transition(self, to: BreakerState) -> None:
        if to is self._state:
            return
        previous = self._state
        self._state = to
        if to is BreakerState.OPEN:
            self._opened_at = self._clock()
        if to is BreakerState.HALF_OPEN:
            self._probes_in_flight = 0
            self._probes_succeeded = 0
        if to is BreakerState.CLOSED:
            self._window.clear()
        metrics.BREAKER_TRANSITIONS.labels(self.name, previous.value, to.value).inc()
        self._publish_state()
        logger.warning("circuit breaker '%s': %s -> %s", self.name, previous.value, to.value)

    def _refresh(self) -> None:
        if (
            self._state is BreakerState.OPEN
            and self._clock() - self._opened_at >= self.config.open_seconds
        ):
            self._transition(BreakerState.HALF_OPEN)

    def _acquire(self) -> _Permit:
        self._refresh()
        now = self._clock()
        if self._state is BreakerState.OPEN:
            self._reject()
        if self._state is BreakerState.HALF_OPEN:
            admitted = self._probes_in_flight + self._probes_succeeded
            if admitted >= self.config.half_open_max_calls:
                self._reject()
            self._probes_in_flight += 1
            return _Permit(self, True, now)
        return _Permit(self, False, now)

    def _reject(self) -> None:
        metrics.BREAKER_REJECTED.labels(self.name).inc()
        raise CircuitOpenError(self.name, self._retry_after())

    def _release(self, permit: _Permit) -> None:
        if permit.probe and self._state is BreakerState.HALF_OPEN:
            self._probes_in_flight = max(0, self._probes_in_flight - 1)

    def _complete(self, permit: _Permit, failed: bool, ignored: bool = False) -> None:
        if permit.done:
            return
        permit.done = True
        now = self._clock()
        threshold = self.config.slow_call_threshold
        slow = threshold is not None and now - permit.started >= threshold
        outcome = "ignored" if ignored else "failure" if failed else ("slow" if slow else "success")
        metrics.BREAKER_CALLS.labels(self.name, outcome).inc()
        if permit.probe:
            self._complete_probe(permit, failed or slow)
            return
        if self._state is not BreakerState.CLOSED:
            return
        self._window.append((now, failed, slow))
        self._trim(now)
        self._evaluate()

    def _complete_probe(self, permit: _Permit, bad: bool) -> None:
        if self._state is not BreakerState.HALF_OPEN:
            return
        self._probes_in_flight = max(0, self._probes_in_flight - 1)
        if bad:
            self._transition(BreakerState.OPEN)
            return
        self._probes_succeeded += 1
        if self._probes_succeeded >= self.config.half_open_max_calls:
            self._transition(BreakerState.CLOSED)

    def _trim(self, now: float) -> None:
        horizon = now - self.config.window_seconds
        while self._window and (
            self._window[0][0] < horizon or len(self._window) > self.config.window_size
        ):
            self._window.popleft()

    def _evaluate(self) -> None:
        total = len(self._window)
        if total < self.config.minimum_calls:
            return
        failures = sum(1 for _, failed, _ in self._window if failed)
        slow = sum(1 for _, _, is_slow in self._window if is_slow)
        if failures / total >= self.config.failure_rate_threshold or (
            self.config.slow_call_threshold is not None
            and slow / total >= self.config.slow_call_rate_threshold
        ):
            self._transition(BreakerState.OPEN)

    @asynccontextmanager
    async def guard(self) -> AsyncIterator[_Permit]:
        permit = self._acquire()
        try:
            yield permit
        except asyncio.CancelledError:
            permit.done = True
            self._release(permit)
            raise
        except BaseException as error:
            if self._is_failure(error):
                self._complete(permit, failed=True)
            else:
                self._complete(permit, failed=False, ignored=True)
            raise
        else:
            self._complete(permit, failed=permit.failed)

    async def call(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        failure_on_result: Callable[[T], bool] | None = None,
    ) -> T:
        async with self.guard() as permit:
            result = await operation()
            if failure_on_result is not None and failure_on_result(result):
                permit.mark_failure()
            return result

    def protect(self, fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            async with self.guard():
                return await fn(*args, **kwargs)

        return wrapper

    __call__ = protect


class BreakerRegistry:
    def __init__(self, *, clock: Clock = monotonic) -> None:
        self._clock = clock
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(
        self,
        name: str,
        config: BreakerConfig | None = None,
        *,
        is_failure: FailurePredicate = _any_exception,
    ) -> CircuitBreaker:
        breaker = self._breakers.get(name)
        if breaker is None:
            breaker = CircuitBreaker(name, config, clock=self._clock, is_failure=is_failure)
            self._breakers[name] = breaker
        return breaker

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {name: b.snapshot() for name, b in self._breakers.items()}
