from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from ledger.domain.errors import InvalidMoney
from ledger.domain.money import Money

BPS_SCALE = 10_000
DEFAULT_FEE_BPS = 1000


def platform_fee(subtotal: Money, fee_bps: int = DEFAULT_FEE_BPS) -> Money:
    if not 0 <= fee_bps <= BPS_SCALE:
        raise InvalidMoney("fee_bps must be between 0 and 10000")
    fee_cents = (subtotal.cents * fee_bps + BPS_SCALE // 2) // BPS_SCALE
    return Money(fee_cents, subtotal.currency)


@dataclass(frozen=True, slots=True)
class MerchantSplit:
    merchant_id: UUID
    gross: Money
    fee: Money
    net: Money


def split_order(
    subtotals: Mapping[UUID, Money], fee_bps: int = DEFAULT_FEE_BPS
) -> list[MerchantSplit]:
    splits: list[MerchantSplit] = []
    for merchant_id in sorted(subtotals, key=str):
        gross = subtotals[merchant_id]
        fee = platform_fee(gross, fee_bps)
        splits.append(MerchantSplit(merchant_id, gross, fee, gross - fee))
    return splits
