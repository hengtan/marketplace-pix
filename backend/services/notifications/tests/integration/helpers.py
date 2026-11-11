from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update

from notifications.infrastructure.db.models import NotificationModel


async def count(session_factory: Any, model: Any) -> int:
    async with session_factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)


async def all_notifications(session_factory: Any) -> list[NotificationModel]:
    async with session_factory() as session:
        return list((await session.execute(select(NotificationModel))).scalars())


async def get_notification(session_factory: Any, notification_id: UUID) -> NotificationModel:
    async with session_factory() as session:
        model = await session.get(NotificationModel, notification_id)
        assert model is not None
        return model


async def age_notification(session_factory: Any, notification_id: UUID, to: datetime) -> None:
    async with session_factory() as session:
        await session.execute(
            update(NotificationModel)
            .where(NotificationModel.id == notification_id)
            .values(next_attempt_at=to)
        )
        await session.commit()
