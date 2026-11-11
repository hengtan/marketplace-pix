from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from marketplace_common.observability import current_traceparent
from sqlalchemy.ext.asyncio import AsyncSession

from payments.domain.events import DomainEvent
from payments.infrastructure.db.models import OutboxEventModel

PAYMENTS_TOPIC = "payments.events"


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def serialize_event(event: DomainEvent) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(json.dumps(asdict(event), default=_json_default))
    return payload


class SqlAlchemyOutbox:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, events: list[DomainEvent]) -> None:
        traceparent = current_traceparent()
        self._session.add_all(
            OutboxEventModel(
                id=event.event_id,
                aggregate_id=event.payment_id,
                topic=PAYMENTS_TOPIC,
                key=str(event.order_id),
                type=type(event).__name__,
                payload=serialize_event(event),
                occurred_at=event.occurred_at,
                traceparent=traceparent,
            )
            for event in events
        )
