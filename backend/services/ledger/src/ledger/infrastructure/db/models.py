from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AccountModel(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    type: Mapped[str] = mapped_column(String(20))
    normal_side: Mapped[str] = mapped_column(String(6))
    currency: Mapped[str] = mapped_column(String(3))
    balance_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrderProjectionModel(Base):
    __tablename__ = "order_projections"

    order_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    currency: Mapped[str] = mapped_column(String(3))
    total_cents: Mapped[int] = mapped_column(BigInteger)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TransactionModel(Base):
    __tablename__ = "ledger_transactions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    order_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    payment_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    currency: Mapped[str] = mapped_column(String(3))
    total_cents: Mapped[int] = mapped_column(BigInteger)
    platform_fee_cents: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EntryModel(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    transaction_id: Mapped[UUID] = mapped_column(ForeignKey("ledger_transactions.id"), index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"))
    direction: Mapped[str] = mapped_column(String(6))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    description: Mapped[str] = mapped_column(String(200))
    order_id: Mapped[UUID] = mapped_column(Uuid)
    merchant_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_entry_amount_positive"),
        CheckConstraint("direction in ('DEBIT', 'CREDIT')", name="ck_entry_direction"),
        Index("ix_entries_account_created", "account_id", "created_at", "id"),
        Index(
            "ix_entries_merchant_created",
            "merchant_id",
            "created_at",
            postgresql_where=text("merchant_id IS NOT NULL"),
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

    __table_args__ = (
        Index(
            "ix_outbox_unpublished",
            "created_at",
            postgresql_where=text("published_at IS NULL"),
        ),
    )
