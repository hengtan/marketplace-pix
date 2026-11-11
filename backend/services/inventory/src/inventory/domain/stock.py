from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from inventory.domain.errors import InsufficientStock, InvalidQuantity


@dataclass(slots=True)
class Stock:
    product_id: UUID
    available: int = 0
    reserved: int = 0
    merchant_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.available < 0 or self.reserved < 0:
            raise InvalidQuantity("stock quantities cannot be negative")

    def can_reserve(self, quantity: int) -> bool:
        return 0 < quantity <= self.available

    def reserve(self, quantity: int) -> None:
        _require_positive(quantity)
        if quantity > self.available:
            raise InsufficientStock(f"only {self.available} available, {quantity} requested")
        self.available -= quantity
        self.reserved += quantity

    def release(self, quantity: int) -> None:
        _require_positive(quantity)
        self._require_reserved(quantity)
        self.reserved -= quantity
        self.available += quantity

    def sell(self, quantity: int) -> None:
        _require_positive(quantity)
        self._require_reserved(quantity)
        self.reserved -= quantity

    def set_available(self, quantity: int) -> None:
        if quantity < 0:
            raise InvalidQuantity("available cannot be negative")
        self.available = quantity

    def _require_reserved(self, quantity: int) -> None:
        if quantity > self.reserved:
            raise InvalidQuantity(f"only {self.reserved} reserved, {quantity} requested")


def _require_positive(quantity: int) -> None:
    if quantity <= 0:
        raise InvalidQuantity("quantity must be positive")
