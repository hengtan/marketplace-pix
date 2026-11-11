from __future__ import annotations

import asyncio
from uuid import UUID


class CeleryNotificationQueue:
    async def enqueue(self, notification_id: UUID) -> None:
        from notifications.worker.tasks import send_notification

        await asyncio.to_thread(send_notification.delay, str(notification_id))
