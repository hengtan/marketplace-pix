from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from notifications.domain.contact import Contact


class OrderStatus(StrEnum):
    PENDING = "PENDING"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class OrderItem:
    product_id: str
    quantity: int
    unit_price_cents: int
    name: str | None = None

    @property
    def line_total_cents(self) -> int:
        return self.quantity * self.unit_price_cents

    def to_json(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "quantity": self.quantity,
            "unit_price_cents": self.unit_price_cents,
            "name": self.name,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> OrderItem:
        return cls(
            product_id=str(data["product_id"]),
            quantity=int(data["quantity"]),
            unit_price_cents=int(data["unit_price_cents"]),
            name=data.get("name") or data.get("product_name"),
        )


@dataclass(slots=True)
class OrderProjection:
    order_id: UUID
    contact: Contact
    currency: str
    total_cents: int
    items: list[OrderItem]
    created_at: datetime
    status: OrderStatus = OrderStatus.PENDING
    paid_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str | None = None

    def mark_paid(self, at: datetime) -> None:
        if self.status is OrderStatus.PENDING:
            self.status = OrderStatus.PAID
            self.paid_at = at

    def mark_cancelled(self, reason: str | None, at: datetime) -> None:
        if self.status is OrderStatus.PENDING:
            self.status = OrderStatus.CANCELLED
            self.cancelled_at = at
            self.cancel_reason = reason
