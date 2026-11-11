from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from notifications.application.clock import Clock, utcnow
from notifications.application.errors import SendError
from notifications.application.ports import EmailRenderer, EmailSender, OutgoingEmail, UnitOfWork
from notifications.domain.notification import NotificationStatus
from notifications.domain.retry import RetryPolicy

logger = logging.getLogger(__name__)


class SendStatus(StrEnum):
    SENT = "SENT"
    SKIPPED = "SKIPPED"
    RETRY = "RETRY"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class SendOutcome:
    status: SendStatus
    retry_in: float | None = None


class SendNotification:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        renderer: EmailRenderer,
        sender: EmailSender,
        policy: RetryPolicy | None = None,
        clock: Clock = utcnow,
    ) -> None:
        self._uow_factory = uow_factory
        self._renderer = renderer
        self._sender = sender
        self._policy = policy or RetryPolicy()
        self._clock = clock

    async def execute(self, notification_id: UUID) -> SendOutcome:
        async with self._uow_factory() as uow:
            notification = await uow.notifications.get_for_sending(notification_id)
            if notification is None or not notification.is_pending:
                return SendOutcome(SendStatus.SKIPPED)

            try:
                rendered = self._renderer.render(notification.kind, notification.context)
                await self._sender.send(
                    OutgoingEmail(
                        to_email=notification.recipient.email,
                        to_name=notification.recipient.name,
                        subject=notification.subject,
                        html=rendered.html,
                        text=rendered.text,
                    )
                )
            except Exception as exc:
                logger.warning("sending notification %s failed: %s", notification.id, exc)
                permanent = isinstance(exc, SendError) and exc.permanent
                notification.record_failure(
                    f"{type(exc).__name__}: {exc}",
                    self._clock(),
                    RetryPolicy(max_attempts=1) if permanent else self._policy,
                )
            else:
                notification.mark_sent(self._clock())

            await uow.notifications.save(notification)
            await uow.commit()

        if notification.status is NotificationStatus.SENT:
            return SendOutcome(SendStatus.SENT)
        if notification.status is NotificationStatus.FAILED:
            return SendOutcome(SendStatus.FAILED)
        return SendOutcome(SendStatus.RETRY, self._policy.delay_after(notification.attempts))
