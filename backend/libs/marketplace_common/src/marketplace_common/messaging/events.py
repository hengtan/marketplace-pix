from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from marketplace_common.events.models import BaseEvent
from marketplace_common.events.registry import REGISTRY

SCHEMA_VERSION_HEADER = "schema_version"

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IncomingEvent:
    id: UUID
    type: str
    key: str
    payload: dict[str, Any]
    schema_version: int = 1

    def parse(self) -> BaseEvent:
        """O evento na versão mais nova que este serviço conhece, já migrado por upcasters."""
        return REGISTRY.parse(self.type, self.payload, self.schema_version)


def header_map(record: Any) -> dict[str, str]:
    return {k: v.decode() for k, v in (record.headers or []) if v is not None}


def to_incoming_event(record: Any) -> IncomingEvent | None:
    try:
        headers = header_map(record)
        payload = json.loads(record.value)
        version = headers.get(SCHEMA_VERSION_HEADER) or payload.get(SCHEMA_VERSION_HEADER) or 1
        return IncomingEvent(
            id=UUID(headers["event_id"]),
            type=headers["event_type"],
            key=record.key.decode(),
            payload=payload,
            schema_version=int(version),
        )
    except (KeyError, ValueError, AttributeError, TypeError):
        logger.error("malformed message skipped (offset %s)", getattr(record, "offset", "?"))
        return None
