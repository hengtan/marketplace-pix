from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

DEFAULT_SCHEMA_VERSION = 1


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def serialize_event(event: object) -> dict[str, Any]:
    """Payload JSON de um evento de domínio. A versão vem do atributo de classe `schema_version`."""
    if not is_dataclass(event) or isinstance(event, type):
        raise TypeError("domain events must be dataclass instances")
    payload: dict[str, Any] = json.loads(json.dumps(asdict(event), default=_json_default))
    payload["schema_version"] = getattr(type(event), "schema_version", DEFAULT_SCHEMA_VERSION)
    return payload
