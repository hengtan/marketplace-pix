from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from ledger.domain.errors import InvalidAccount

PSP_RECEIVABLE_ID = "psp:receivable"
PLATFORM_REVENUE_ID = "platform:revenue"
MERCHANT_PREFIX = "merchant:"


class Direction(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class AccountType(StrEnum):
    ASSET = "ASSET"
    REVENUE = "REVENUE"
    LIABILITY = "LIABILITY"

    @property
    def normal_side(self) -> Direction:
        return Direction.DEBIT if self is AccountType.ASSET else Direction.CREDIT


def merchant_account_id(merchant_id: UUID) -> str:
    return f"{MERCHANT_PREFIX}{merchant_id}"


@dataclass(frozen=True, slots=True)
class Account:
    id: str
    type: AccountType

    @property
    def normal_side(self) -> Direction:
        return self.type.normal_side

    def signed_amount(self, direction: Direction, cents: int) -> int:
        return cents if direction is self.normal_side else -cents

    @classmethod
    def psp_receivable(cls) -> Account:
        return cls(PSP_RECEIVABLE_ID, AccountType.ASSET)

    @classmethod
    def platform_revenue(cls) -> Account:
        return cls(PLATFORM_REVENUE_ID, AccountType.REVENUE)

    @classmethod
    def merchant(cls, merchant_id: UUID) -> Account:
        return cls(merchant_account_id(merchant_id), AccountType.LIABILITY)

    @classmethod
    def from_id(cls, account_id: str) -> Account:
        if account_id == PSP_RECEIVABLE_ID:
            return cls.psp_receivable()
        if account_id == PLATFORM_REVENUE_ID:
            return cls.platform_revenue()
        if account_id.startswith(MERCHANT_PREFIX):
            try:
                return cls.merchant(UUID(account_id.removeprefix(MERCHANT_PREFIX)))
            except ValueError:
                pass
        raise InvalidAccount(f"unknown account {account_id!r}")
