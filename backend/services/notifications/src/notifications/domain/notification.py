from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from notifications.domain.contact import Contact
from notifications.domain.retry import RetryPolicy


class NotificationKind(StrEnum):
    ORDER_CREATED = "ORDER_CREATED"
    PIX_READY = "PIX_READY"
    ORDER_PAID = "ORDER_PAID"
    ORDER_CANCELLED = "ORDER_CANCELLED"


class NotificationStatus(StrEnum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    FAILED = "FAILED"


@dataclass(slots=True)
class Notification:
    id: UUID
    event_id: UUID
    kind: NotificationKind
    order_id: UUID
    recipient: Contact
    subject: str
    context: dict[str, Any]
    created_at: datetime
    next_attempt_at: datetime
    status: NotificationStatus = NotificationStatus.QUEUED
    attempts: int = 0
    last_error: str | None = None
    sent_at: datetime | None = None

    @property
    def is_pending(self) -> bool:
        return self.status is NotificationStatus.QUEUED

    def mark_sent(self, now: datetime) -> None:
        self.attempts += 1
        self.status = NotificationStatus.SENT
        self.sent_at = now
        self.last_error = None

    def record_failure(self, error: str, now: datetime, policy: RetryPolicy) -> None:
        self.attempts += 1
        self.last_error = error[:500]
        if policy.exhausted(self.attempts):
            self.status = NotificationStatus.FAILED
        else:
            self.next_attempt_at = now + timedelta(seconds=policy.delay_after(self.attempts))
