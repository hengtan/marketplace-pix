from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from notifications.domain.notification import Notification


class NotificationOut(BaseModel):
    id: UUID
    kind: str
    subject: str
    status: str
    order_id: UUID
    created_at: datetime
    sent_at: datetime | None

    @classmethod
    def from_domain(cls, notification: Notification) -> NotificationOut:
        return cls(
            id=notification.id,
            kind=notification.kind.value,
            subject=notification.subject,
            status=notification.status.value,
            order_id=notification.order_id,
            created_at=notification.created_at,
            sent_at=notification.sent_at,
        )


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    total: int
    page: int
    page_size: int
