from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class Outcome(StrEnum):
    PROCESSED = "PROCESSED"
    DUPLICATE = "DUPLICATE"
    IGNORED = "IGNORED"


@dataclass(frozen=True, slots=True)
class Delivery:
    event_id: UUID
    consumer: str


class ApplicationError(Exception):
    pass


class ReservationNotFound(ApplicationError):
    pass
