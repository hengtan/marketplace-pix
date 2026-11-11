from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta

from notifications.application.clock import Clock, utcnow
from notifications.application.ports import NotificationQueue, UnitOfWork

logger = logging.getLogger(__name__)


class RequeueStaleNotifications:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        queue: NotificationQueue,
        stale_after: timedelta = timedelta(seconds=60),
        batch_size: int = 100,
        clock: Clock = utcnow,
    ) -> None:
        self._uow_factory = uow_factory
        self._queue = queue
        self._stale_after = stale_after
        self._batch_size = batch_size
        self._clock = clock

    async def execute(self) -> int:
        now = self._clock()
        async with self._uow_factory() as uow:
            stale = await uow.notifications.fetch_stale_queued(
                now - self._stale_after, self._batch_size
            )
            await uow.notifications.touch([n.id for n in stale], now)
            await uow.commit()

        enqueued = 0
        for notification in stale:
            try:
                await self._queue.enqueue(notification.id)
            except Exception:
                logger.exception("could not requeue notification %s", notification.id)
            else:
                enqueued += 1
        return enqueued
