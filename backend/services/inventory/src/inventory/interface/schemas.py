from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from inventory.domain.stock import Stock


class StockOut(BaseModel):
    product_id: UUID
    available: int
    reserved: int

    @classmethod
    def from_domain(cls, stock: Stock) -> StockOut:
        return cls(product_id=stock.product_id, available=stock.available, reserved=stock.reserved)


class SetStockIn(BaseModel):
    available: int = Field(ge=0)
