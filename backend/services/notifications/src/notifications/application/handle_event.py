from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from notifications.application.clock import Clock, utcnow
from notifications.application.errors import OrderContextMissing
from notifications.application.ports import (
    IncomingEvent,
    NotificationQueue,
    UnitOfWork,
)
from notifications.domain.contact import Contact
from notifications.domain.errors import DomainError
from notifications.domain.factory import build_notification
from notifications.domain.notification import Notification, NotificationKind
from notifications.domain.order_projection import OrderItem, OrderProjection

CONSUMER_NAME = "notifications"
HANDLED_TYPES = frozenset({"OrderCreated", "OrderPaid", "OrderCancelled", "PaymentCreated"})

logger = logging.getLogger(__name__)


class HandleResult(StrEnum):
    PROCESSED = "PROCESSED"
    DUPLICATE = "DUPLICATE"
    IGNORED = "IGNORED"


def _parse_time(value: Any, fallback: datetime) -> datetime:
    return datetime.fromisoformat(value) if isinstance(value, str) else fallback


class HandleEvent:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        queue: NotificationQueue,
        base_url: str = "http://localhost:5173",
        clock: Clock = utcnow,
    ) -> None:
        self._uow_factory = uow_factory
        self._queue = queue
        self._base_url = base_url
        self._clock = clock

    async def handle(self, event: IncomingEvent) -> HandleResult:
        if event.type not in HANDLED_TYPES:
            return HandleResult.IGNORED
        async with self._uow_factory() as uow:
            if not await uow.inbox.claim(event.id, CONSUMER_NAME):
                return HandleResult.DUPLICATE
            try:
                notification = await self._apply(uow, event)
            except (KeyError, ValueError, TypeError, DomainError):
                logger.exception("malformed %s event %s skipped", event.type, event.id)
                return HandleResult.IGNORED
            created = await uow.notifications.add(notification)
            await uow.commit()
        if created:
            await self._enqueue(notification.id)
        return HandleResult.PROCESSED

    async def _enqueue(self, notification_id: UUID) -> None:
        try:
            await self._queue.enqueue(notification_id)
        except Exception:
            logger.exception(
                "could not enqueue notification %s, the requeue sweep will pick it up",
                notification_id,
            )

    async def _apply(self, uow: UnitOfWork, event: IncomingEvent) -> Notification:
        now = self._clock()
        payload = event.payload
        order_id = UUID(payload["order_id"])

        if event.type == "OrderCreated":
            order = await uow.orders.get(order_id)
            if order is None:
                order = self._projection_from(payload, order_id, now)
                await uow.orders.add(order)
            return build_notification(
                NotificationKind.ORDER_CREATED, event.id, order, now, base_url=self._base_url
            )

        order = await uow.orders.get(order_id)
        if order is None:
            raise OrderContextMissing(str(order_id))

        if event.type == "PaymentCreated":
            return build_notification(
                NotificationKind.PIX_READY,
                event.id,
                order,
                now,
                base_url=self._base_url,
                pix_code=str(payload["pix_code"]),
                pix_amount_cents=int(payload["amount_cents"]),
                pix_expires_at=datetime.fromisoformat(payload["expires_at"]),
            )
        occurred_at = _parse_time(payload.get("occurred_at"), now)
        if event.type == "OrderPaid":
            order.mark_paid(occurred_at)
            await uow.orders.save(order)
            return build_notification(
                NotificationKind.ORDER_PAID, event.id, order, now, base_url=self._base_url
            )
        reason = payload.get("reason")
        order.mark_cancelled(reason, occurred_at)
        await uow.orders.save(order)
        return build_notification(
            NotificationKind.ORDER_CANCELLED,
            event.id,
            order,
            now,
            base_url=self._base_url,
            reason=reason,
        )

    @staticmethod
    def _projection_from(payload: dict[str, Any], order_id: UUID, now: datetime) -> OrderProjection:
        return OrderProjection(
            order_id=order_id,
            contact=Contact(
                UUID(payload["customer_id"]), payload["customer_name"], payload["customer_email"]
            ),
            currency=payload["currency"],
            total_cents=int(payload["total_cents"]),
            items=[OrderItem.from_json(item) for item in payload["items"]],
            created_at=_parse_time(payload.get("occurred_at"), now),
        )
