from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from inventory.domain.stock import Stock


class StockOut(BaseModel):
    """`reserved` só aparece para o lojista dono do produto (ou o admin): para o público é um dado
    operacional que revela a demanda."""

    product_id: UUID
    available: int
    reserved: int | None = None

    @classmethod
    def from_domain(cls, stock: Stock, include_reserved: bool = False) -> StockOut:
        return cls(
            product_id=stock.product_id,
            available=stock.available,
            reserved=stock.reserved if include_reserved else None,
        )


class SetStockIn(BaseModel):
    available: int = Field(ge=0)
