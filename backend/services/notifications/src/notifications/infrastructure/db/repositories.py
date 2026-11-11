from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from notifications.application.ports import DailyStats
from notifications.domain.contact import Contact
from notifications.domain.notification import Notification, NotificationKind, NotificationStatus
from notifications.domain.order_projection import OrderItem, OrderProjection, OrderStatus
from notifications.infrastructure.db.models import NotificationModel, OrderProjectionModel


def _notification_to_domain(model: NotificationModel) -> Notification:
    return Notification(
        id=model.id,
        event_id=model.event_id,
        kind=NotificationKind(model.kind),
        order_id=model.order_id,
        recipient=Contact(model.customer_id, model.recipient_name, model.recipient_email),
        subject=model.subject,
        context=model.context,
        created_at=model.created_at,
        next_attempt_at=model.next_attempt_at,
        status=NotificationStatus(model.status),
        attempts=model.attempts,
        last_error=model.last_error,
        sent_at=model.sent_at,
    )


class SqlAlchemyNotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, notification: Notification) -> bool:
        stmt = (
            insert(NotificationModel)
            .values(
                id=notification.id,
                event_id=notification.event_id,
                kind=notification.kind.value,
                order_id=notification.order_id,
                customer_id=notification.recipient.customer_id,
                recipient_name=notification.recipient.name,
                recipient_email=notification.recipient.email,
                subject=notification.subject,
                context=notification.context,
                status=notification.status.value,
                attempts=notification.attempts,
                next_attempt_at=notification.next_attempt_at,
                created_at=notification.created_at,
            )
            .on_conflict_do_nothing(constraint="uq_notifications_event_kind")
            .returning(NotificationModel.id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def get(self, notification_id: UUID) -> Notification | None:
        model = await self._session.get(NotificationModel, notification_id)
        return None if model is None else _notification_to_domain(model)

    async def get_for_sending(self, notification_id: UUID) -> Notification | None:
        stmt = (
            select(NotificationModel)
            .where(NotificationModel.id == notification_id)
            .with_for_update(skip_locked=True)
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if model is None else _notification_to_domain(model)

    async def save(self, notification: Notification) -> None:
        model = await self._session.get(NotificationModel, notification.id)
        if model is None:
            raise LookupError(f"notification {notification.id} not found")
        model.status = notification.status.value
        model.attempts = notification.attempts
        model.last_error = notification.last_error
        model.next_attempt_at = notification.next_attempt_at
        model.sent_at = notification.sent_at

    async def list_page(
        self, customer_id: UUID | None, page: int, page_size: int
    ) -> tuple[list[Notification], int]:
        filters = [] if customer_id is None else [NotificationModel.customer_id == customer_id]
        total = await self._session.scalar(
            select(func.count()).select_from(NotificationModel).where(*filters)
        )
        stmt = (
            select(NotificationModel)
            .where(*filters)
            .order_by(NotificationModel.created_at.desc(), NotificationModel.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_notification_to_domain(m) for m in rows], total or 0

    async def fetch_stale_queued(self, before: datetime, limit: int) -> list[Notification]:
        stmt = (
            select(NotificationModel)
            .where(NotificationModel.status == NotificationStatus.QUEUED.value)
            .where(NotificationModel.next_attempt_at <= before)
            .order_by(NotificationModel.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [_notification_to_domain(m) for m in (await self._session.execute(stmt)).scalars()]

    async def touch(self, ids: list[UUID], now: datetime) -> None:
        if not ids:
            return
        await self._session.execute(
            update(NotificationModel)
            .where(NotificationModel.id.in_(ids))
            .values(next_attempt_at=now)
        )


def _order_to_domain(model: OrderProjectionModel) -> OrderProjection:
    return OrderProjection(
        order_id=model.order_id,
        contact=Contact(model.customer_id, model.customer_name, model.customer_email),
        currency=model.currency,
        total_cents=model.total_cents,
        items=[OrderItem.from_json(item) for item in model.items],
        created_at=model.created_at,
        status=OrderStatus(model.status),
        paid_at=model.paid_at,
        cancelled_at=model.cancelled_at,
        cancel_reason=model.cancel_reason,
    )


class SqlAlchemyOrderProjectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, order: OrderProjection) -> None:
        self._session.add(
            OrderProjectionModel(
                order_id=order.order_id,
                customer_id=order.contact.customer_id,
                customer_name=order.contact.name,
                customer_email=order.contact.email,
                currency=order.currency,
                total_cents=order.total_cents,
                items=[item.to_json() for item in order.items],
                status=order.status.value,
                created_at=order.created_at,
                paid_at=order.paid_at,
                cancelled_at=order.cancelled_at,
                cancel_reason=order.cancel_reason,
            )
        )

    async def get(self, order_id: UUID) -> OrderProjection | None:
        model = await self._session.get(OrderProjectionModel, order_id)
        return None if model is None else _order_to_domain(model)

    async def save(self, order: OrderProjection) -> None:
        model = await self._session.get(OrderProjectionModel, order.order_id)
        if model is None:
            raise LookupError(f"order {order.order_id} not found")
        model.status = order.status.value
        model.paid_at = order.paid_at
        model.cancelled_at = order.cancelled_at
        model.cancel_reason = order.cancel_reason

    async def stats_between(self, start: datetime, end: datetime) -> DailyStats:
        m = OrderProjectionModel
        stmt = select(
            func.count().filter(m.created_at >= start, m.created_at < end),
            func.count().filter(m.paid_at >= start, m.paid_at < end),
            func.count().filter(m.cancelled_at >= start, m.cancelled_at < end),
            func.coalesce(func.sum(m.total_cents).filter(m.paid_at >= start, m.paid_at < end), 0),
        )
        created, paid, cancelled, paid_cents = (await self._session.execute(stmt)).one()
        return DailyStats(int(created), int(paid), int(cancelled), int(paid_cents))
