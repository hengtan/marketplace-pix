from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from ordering.domain.order import Order


class OrderItemIn(BaseModel):
    product_id: UUID
    quantity: int = Field(gt=0)
    unit_price_cents: int = Field(ge=0)


class CreateOrderIn(BaseModel):
    customer_id: UUID
    items: list[OrderItemIn] = Field(min_length=1)
    currency: str = Field(default="BRL", pattern=r"^[A-Z]{3}$")


class CreateOrderOut(BaseModel):
    id: UUID


class OrderItemOut(BaseModel):
    product_id: UUID
    quantity: int
    unit_price_cents: int


class OrderOut(BaseModel):
    id: UUID
    customer_id: UUID
    status: str
    currency: str
    total_cents: int
    items: list[OrderItemOut]

    @classmethod
    def from_domain(cls, order: Order) -> OrderOut:
        return cls(
            id=order.id,
            customer_id=order.customer_id,
            status=order.status.value,
            currency=order.total.currency,
            total_cents=order.total.cents,
            items=[
                OrderItemOut(
                    product_id=i.product_id,
                    quantity=i.quantity,
                    unit_price_cents=i.unit_price.cents,
                )
                for i in order.items
            ],
        )
