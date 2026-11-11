from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IncomingEvent:
    id: UUID
    type: str
    key: str
    payload: dict[str, Any]


def header_map(record: Any) -> dict[str, str]:
    return {k: v.decode() for k, v in (record.headers or []) if v is not None}


def to_incoming_event(record: Any) -> IncomingEvent | None:
    try:
        headers = header_map(record)
        return IncomingEvent(
            id=UUID(headers["event_id"]),
            type=headers["event_type"],
            key=record.key.decode(),
            payload=json.loads(record.value),
        )
    except (KeyError, ValueError, AttributeError):
        logger.error("malformed message skipped (offset %s)", getattr(record, "offset", "?"))
        return None
