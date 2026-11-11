from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EventModel(BaseModel):
    """Contrato de um evento em uma versão. Campos desconhecidos são ignorados na leitura."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    event_type: ClassVar[str]
    version: ClassVar[int]

    schema_version: int
    event_id: UUID
    occurred_at: datetime
    order_id: UUID


class OrderItemV1(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    product_id: UUID
    merchant_id: UUID
    quantity: int
    unit_price_cents: int


class OrderCreatedV1(EventModel):
    event_type = "OrderCreated"
    version = 1

    schema_version: Literal[1] = 1
    customer_id: UUID
    customer_name: str
    customer_email: str
    total_cents: int
    currency: str
    items: tuple[OrderItemV1, ...]


class OrderCreatedV2(EventModel):
    """v2 acrescenta `customer_type` (opcional): `guest` ou `registered`."""

    event_type = "OrderCreated"
    version = 2

    schema_version: Literal[2] = 2
    customer_id: UUID
    customer_name: str
    customer_email: str
    total_cents: int
    currency: str
    items: tuple[OrderItemV1, ...]
    customer_type: Literal["guest", "registered"] | None = None


class OrderPaidV1(EventModel):
    event_type = "OrderPaid"
    version = 1

    schema_version: Literal[1] = 1


class OrderCancelledV1(EventModel):
    event_type = "OrderCancelled"
    version = 1

    schema_version: Literal[1] = 1
    reason: str


class PaymentEventModel(EventModel):
    payment_id: UUID


class PaymentCreatedV1(PaymentEventModel):
    event_type = "PaymentCreated"
    version = 1

    schema_version: Literal[1] = 1
    amount_cents: int
    currency: str
    pix_code: str
    expires_at: datetime


class PaymentConfirmedV1(PaymentEventModel):
    event_type = "PaymentConfirmed"
    version = 1

    schema_version: Literal[1] = 1
    amount_cents: int
    currency: str


class PaymentExpiredV1(PaymentEventModel):
    event_type = "PaymentExpired"
    version = 1

    schema_version: Literal[1] = 1


class PaymentCancelledV1(PaymentEventModel):
    event_type = "PaymentCancelled"
    version = 1

    schema_version: Literal[1] = 1


class ShortageV1(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    product_id: UUID
    requested: int
    available: int


class StockReservedV1(EventModel):
    event_type = "StockReserved"
    version = 1

    schema_version: Literal[1] = 1


class StockRejectedV1(EventModel):
    event_type = "StockRejected"
    version = 1

    schema_version: Literal[1] = 1
    reason: str
    missing: tuple[ShortageV1, ...]


class StockCommittedV1(EventModel):
    event_type = "StockCommitted"
    version = 1

    schema_version: Literal[1] = 1


class StockReleasedV1(EventModel):
    event_type = "StockReleased"
    version = 1

    schema_version: Literal[1] = 1
    reason: str


class LedgerTransactionPostedV1(EventModel):
    event_type = "LedgerTransactionPosted"
    version = 1

    schema_version: Literal[1] = 1
    transaction_id: UUID
    total_cents: int
    platform_fee_cents: int
