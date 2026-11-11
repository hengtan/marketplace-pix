from __future__ import annotations

import asyncio
import functools
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import ParamSpec, TypeVar

from marketplace_common.resilience import metrics
from marketplace_common.resilience.clock import Clock, monotonic
from marketplace_common.resilience.errors import BulkheadFullError

P = ParamSpec("P")
T = TypeVar("T")

Waiter = Callable[[Awaitable[bool], float], Awaitable[bool]]


async def _wait_for(awaitable: Awaitable[bool], timeout: float) -> bool:
    return await asyncio.wait_for(awaitable, timeout)


class Bulkhead:
    """Semáforo por dependência com fila limitada: quando enche, falha rápido em vez de empilhar."""

    def __init__(
        self,
        name: str,
        max_concurrent: int = 10,
        max_queue: int = 0,
        queue_timeout: float = 0.5,
        *,
        clock: Clock = monotonic,
        waiter: Waiter = _wait_for,
        retry_after: float = 1.0,
    ) -> None:
        if max_concurrent < 1 or max_queue < 0 or queue_timeout < 0:
            raise ValueError("invalid bulkhead configuration")
        self.name = name
        self.max_concurrent = max_concurrent
        self.max_queue = max_queue
        self._queue_timeout = queue_timeout
        self._clock = clock
        self._waiter = waiter
        self._retry_after = retry_after
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._in_flight = 0
        self._queued = 0
        metrics.BULKHEAD_IN_FLIGHT.labels(name).set(0)
        metrics.BULKHEAD_QUEUED.labels(name).set(0)

    @property
    def in_flight(self) -> int:
        return self._in_flight

    @property
    def queued(self) -> int:
        return self._queued

    def _reject(self, reason: str) -> BulkheadFullError:
        metrics.BULKHEAD_REJECTED.labels(self.name, reason).inc()
        return BulkheadFullError(self.name, reason, self._retry_after)

    async def _acquire(self) -> None:
        if not self._semaphore.locked():
            await self._semaphore.acquire()
            return
        if self._queued >= self.max_queue:
            raise self._reject("full")
        self._queued += 1
        metrics.BULKHEAD_QUEUED.labels(self.name).set(self._queued)
        started = self._clock()
        try:
            await self._waiter(self._semaphore.acquire(), self._queue_timeout)
        except TimeoutError:
            raise self._reject("timeout") from None
        finally:
            self._queued -= 1
            metrics.BULKHEAD_QUEUED.labels(self.name).set(self._queued)
            metrics.BULKHEAD_WAIT.labels(self.name).observe(self._clock() - started)

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        await self._acquire()
        self._in_flight += 1
        metrics.BULKHEAD_IN_FLIGHT.labels(self.name).set(self._in_flight)
        try:
            yield
        finally:
            self._in_flight -= 1
            metrics.BULKHEAD_IN_FLIGHT.labels(self.name).set(self._in_flight)
            self._semaphore.release()

    async def call(self, operation: Callable[[], Awaitable[T]]) -> T:
        async with self.slot():
            return await operation()

    def protect(self, fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            async with self.slot():
                return await fn(*args, **kwargs)

        return wrapper

    __call__ = protect
