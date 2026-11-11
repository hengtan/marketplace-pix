from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ledger.domain.account import Account, Direction
from ledger.domain.errors import PaymentMismatch
from ledger.domain.money import Money
from ledger.domain.order_projection import OrderProjection
from ledger.domain.split import DEFAULT_FEE_BPS, split_order
from ledger.domain.transaction import Entry, Transaction, TransactionKind


def build_payment_transaction(
    projection: OrderProjection,
    payment_id: UUID,
    amount: Money,
    created_at: datetime,
    fee_bps: int = DEFAULT_FEE_BPS,
) -> Transaction:
    if amount != projection.total:
        raise PaymentMismatch(
            f"payment of {amount.cents} {amount.currency} does not match "
            f"order total {projection.total.cents} {projection.total.currency}"
        )
    short_id = str(projection.order_id)[:8]
    entries = [
        Entry(
            Account.psp_receivable(),
            Direction.DEBIT,
            amount,
            f"Recebimento do pedido {short_id}",
        )
    ]
    fees = Money.zero(projection.currency)
    for split in split_order(projection.merchant_subtotals(), fee_bps):
        if not split.net.is_zero:
            entries.append(
                Entry(
                    Account.merchant(split.merchant_id),
                    Direction.CREDIT,
                    split.net,
                    f"Venda do pedido {short_id} (líquido)",
                    merchant_id=split.merchant_id,
                )
            )
        if not split.fee.is_zero:
            entries.append(
                Entry(
                    Account.platform_revenue(),
                    Direction.CREDIT,
                    split.fee,
                    f"Taxa da plataforma sobre o pedido {short_id}",
                    merchant_id=split.merchant_id,
                )
            )
            fees = fees + split.fee
    return Transaction.post(
        order_id=projection.order_id,
        payment_id=payment_id,
        entries=entries,
        created_at=created_at,
        platform_fee=fees,
    )


def build_reversal_transaction(
    projection: OrderProjection,
    payment_id: UUID,
    amount: Money,
    created_at: datetime,
    fee_bps: int = DEFAULT_FEE_BPS,
) -> Transaction:
    original = build_payment_transaction(projection, payment_id, amount, created_at, fee_bps)
    short_id = str(projection.order_id)[:8]
    flipped = {Direction.DEBIT: Direction.CREDIT, Direction.CREDIT: Direction.DEBIT}
    entries = [
        Entry(
            entry.account,
            flipped[entry.direction],
            entry.amount,
            f"Estorno do pedido {short_id}: {entry.description}",
            merchant_id=entry.merchant_id,
        )
        for entry in original.entries
    ]
    return Transaction.post(
        order_id=projection.order_id,
        payment_id=payment_id,
        entries=entries,
        created_at=created_at,
        platform_fee=original.platform_fee,
        kind=TransactionKind.REVERSAL,
    )
