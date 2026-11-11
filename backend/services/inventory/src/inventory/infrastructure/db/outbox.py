from __future__ import annotations

from typing import Any

from marketplace_common.events import serialize_event as serialize
from marketplace_common.observability import current_traceparent
from sqlalchemy.ext.asyncio import AsyncSession

from inventory.domain.events import DomainEvent
from inventory.infrastructure.db.models import OutboxEventModel

INVENTORY_TOPIC = "inventory.events"


def serialize_event(event: DomainEvent) -> dict[str, Any]:
    return serialize(event)


class SqlAlchemyOutbox:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, events: list[DomainEvent]) -> None:
        traceparent = current_traceparent()
        self._session.add_all(
            OutboxEventModel(
                id=event.event_id,
                aggregate_id=event.order_id,
                topic=INVENTORY_TOPIC,
                key=str(event.order_id),
                type=type(event).__name__,
                payload=serialize_event(event),
                occurred_at=event.occurred_at,
                traceparent=traceparent,
            )
            for event in events
        )
