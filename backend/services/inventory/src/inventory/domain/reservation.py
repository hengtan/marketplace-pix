from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from inventory.domain.errors import InvalidReservation, InvalidStateTransition
from inventory.domain.events import (
    DomainEvent,
    Shortage,
    StockCommitted,
    StockRejected,
    StockReleased,
    StockReserved,
)
from inventory.domain.stock import Stock

INSUFFICIENT_STOCK = "insufficient_stock"


class ReservationStatus(StrEnum):
    RESERVED = "RESERVED"
    REJECTED = "REJECTED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


@dataclass(frozen=True, slots=True)
class ReservationItem:
    product_id: UUID
    quantity: int

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise InvalidReservation("item quantity must be positive")


def merge_items(items: Iterable[ReservationItem]) -> list[ReservationItem]:
    totals: dict[UUID, int] = {}
    for item in items:
        totals[item.product_id] = totals.get(item.product_id, 0) + item.quantity
    if not totals:
        raise InvalidReservation("a reservation needs at least one item")
    return [ReservationItem(product_id, quantity) for product_id, quantity in totals.items()]


@dataclass(slots=True)
class Reservation:
    order_id: UUID
    items: list[ReservationItem]
    status: ReservationStatus
    expires_at: datetime
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    @classmethod
    def place(
        cls,
        order_id: UUID,
        items: Iterable[ReservationItem],
        stocks: Mapping[UUID, Stock],
        now: datetime,
        ttl: timedelta,
    ) -> Reservation:
        merged = merge_items(items)
        missing = [
            Shortage(
                product_id=item.product_id,
                requested=item.quantity,
                available=stocks[item.product_id].available if item.product_id in stocks else 0,
            )
            for item in merged
            if item.product_id not in stocks
            or not stocks[item.product_id].can_reserve(item.quantity)
        ]
        if missing:
            rejected = cls(order_id, merged, ReservationStatus.REJECTED, now)
            rejected._events.append(
                StockRejected(order_id=order_id, reason=INSUFFICIENT_STOCK, missing=missing)
            )
            return rejected
        for item in merged:
            stocks[item.product_id].reserve(item.quantity)
        reserved = cls(order_id, merged, ReservationStatus.RESERVED, now + ttl)
        reserved._events.append(StockReserved(order_id=order_id))
        return reserved

    @property
    def product_ids(self) -> list[UUID]:
        return sorted({item.product_id for item in self.items})

    def commit(self, stocks: Mapping[UUID, Stock]) -> None:
        self._require_reserved("committed")
        for item in self.items:
            stocks[item.product_id].sell(item.quantity)
        self.status = ReservationStatus.COMMITTED
        self._events.append(StockCommitted(order_id=self.order_id))

    def release(self, stocks: Mapping[UUID, Stock], reason: str) -> None:
        self._require_reserved("released")
        for item in self.items:
            stocks[item.product_id].release(item.quantity)
        self.status = ReservationStatus.RELEASED
        self._events.append(StockReleased(order_id=self.order_id, reason=reason))

    def is_expired(self, now: datetime) -> bool:
        return self.status is ReservationStatus.RESERVED and self.expires_at <= now

    def pull_events(self) -> list[DomainEvent]:
        events, self._events = self._events, []
        return events

    def _require_reserved(self, action: str) -> None:
        if self.status is not ReservationStatus.RESERVED:
            raise InvalidStateTransition(f"reservation {self.status} cannot be {action}")
