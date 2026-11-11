from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from ordering.application.list_orders import OrderPage
from ordering.domain.order import Order


class OrderItemIn(BaseModel):
    product_id: UUID
    quantity: int = Field(ge=1, le=99)


class CreateOrderIn(BaseModel):
    customer_id: UUID | None = None
    customer_name: str = Field(min_length=1, max_length=120)
    customer_email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    items: list[OrderItemIn] = Field(min_length=1, max_length=50)


class CreateOrderOut(BaseModel):
    id: UUID


class OrderItemOut(BaseModel):
    product_id: UUID
    merchant_id: UUID
    quantity: int
    unit_price_cents: int


class OrderOut(BaseModel):
    id: UUID
    customer_id: UUID
    customer_name: str
    customer_email: str
    status: str
    currency: str
    total_cents: int
    created_at: datetime | None
    cancel_reason: str | None
    items: list[OrderItemOut]

    @classmethod
    def from_domain(cls, order: Order) -> OrderOut:
        return cls(
            id=order.id,
            customer_id=order.customer_id,
            customer_name=order.customer_name,
            customer_email=order.customer_email,
            status=order.status.value,
            currency=order.total.currency,
            total_cents=order.total.cents,
            created_at=order.created_at,
            cancel_reason=order.cancel_reason,
            items=[
                OrderItemOut(
                    product_id=i.product_id,
                    merchant_id=i.merchant_id,
                    quantity=i.quantity,
                    unit_price_cents=i.unit_price.cents,
                )
                for i in order.items
            ],
        )


class MerchantOrderOut(BaseModel):
    id: UUID
    status: str
    currency: str
    created_at: datetime | None
    customer_name: str
    subtotal_cents: int
    items: list[OrderItemOut]

    @classmethod
    def from_domain(cls, order: Order, merchant_id: UUID) -> MerchantOrderOut:
        mine = order.items_of(merchant_id)
        return cls(
            id=order.id,
            status=order.status.value,
            currency=order.total.currency,
            created_at=order.created_at,
            customer_name=order.customer_name,
            subtotal_cents=sum(i.subtotal.cents for i in mine),
            items=[
                OrderItemOut(
                    product_id=i.product_id,
                    merchant_id=i.merchant_id,
                    quantity=i.quantity,
                    unit_price_cents=i.unit_price.cents,
                )
                for i in mine
            ],
        )


class MerchantOrderPageOut(BaseModel):
    items: list[MerchantOrderOut]
    total: int
    page: int
    page_size: int

    @classmethod
    def from_domain(cls, page: OrderPage, merchant_id: UUID) -> MerchantOrderPageOut:
        return cls(
            items=[MerchantOrderOut.from_domain(o, merchant_id) for o in page.items],
            total=page.total,
            page=page.page,
            page_size=page.page_size,
        )


class OrderPageOut(BaseModel):
    items: list[OrderOut]
    total: int
    page: int
    page_size: int

    @classmethod
    def from_domain(cls, page: OrderPage) -> OrderPageOut:
        return cls(
            items=[OrderOut.from_domain(o) for o in page.items],
            total=page.total,
            page=page.page,
            page_size=page.page_size,
        )
