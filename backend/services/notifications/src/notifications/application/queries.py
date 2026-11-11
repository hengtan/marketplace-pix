from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from notifications.application.errors import NotificationNotFound
from notifications.application.ports import EmailRenderer, UnitOfWork
from notifications.domain.notification import Notification


class ListNotifications:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def execute(
        self, customer_id: UUID | None, page: int, page_size: int
    ) -> tuple[list[Notification], int]:
        async with self._uow_factory() as uow:
            return await uow.notifications.list_page(customer_id, page, page_size)


class PreviewNotification:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], renderer: EmailRenderer) -> None:
        self._uow_factory = uow_factory
        self._renderer = renderer

    async def execute(self, notification_id: UUID) -> str:
        async with self._uow_factory() as uow:
            notification = await uow.notifications.get(notification_id)
        if notification is None:
            raise NotificationNotFound(str(notification_id))
        return self._renderer.render(notification.kind, notification.context).html
