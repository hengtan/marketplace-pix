from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Index, String, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PaymentModel(Base):
    __tablename__ = "payments"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    order_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    status: Mapped[str] = mapped_column(String(20))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    psp_charge_id: Mapped[str] = mapped_column(String(100), unique=True)
    pix_code: Mapped[str] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index(
            "ix_payments_pending_expiry",
            "expires_at",
            postgresql_where=text("status = 'PENDING'"),
        ),
    )


class InboxMessageModel(Base):
    __tablename__ = "inbox_messages"

    message_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    consumer: Mapped[str] = mapped_column(String(100), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OutboxEventModel(Base):
    __tablename__ = "outbox_events"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    aggregate_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    topic: Mapped[str] = mapped_column(String(100))
    key: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    traceparent: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index(
            "ix_outbox_unpublished",
            "created_at",
            postgresql_where=text("published_at IS NULL"),
        ),
    )


class SimulatedChargeModel(Base):
    """Estado do PSP simulado: representa o sistema EXTERNO, não o nosso domínio."""

    __tablename__ = "simulated_psp_charges"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    reference: Mapped[str] = mapped_column(String(100), unique=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20))
    pix_code: Mapped[str] = mapped_column(String(500))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
