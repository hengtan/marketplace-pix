from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from ledger.domain.account import Account, Direction
from ledger.domain.errors import InvalidTransaction, UnbalancedTransaction
from ledger.domain.events import DomainEvent, LedgerTransactionPosted
from ledger.domain.money import Money


@dataclass(frozen=True, slots=True)
class Entry:
    account: Account
    direction: Direction
    amount: Money
    description: str
    merchant_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if self.amount.cents <= 0:
            raise InvalidTransaction("entry amount must be positive")

    @property
    def signed_balance_delta(self) -> int:
        return self.account.signed_amount(self.direction, self.amount.cents)


@dataclass(slots=True)
class Transaction:
    id: UUID
    order_id: UUID
    payment_id: UUID
    currency: str
    entries: tuple[Entry, ...]
    created_at: datetime
    platform_fee: Money
    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if len(self.entries) < 2:
            raise InvalidTransaction("a transaction needs at least two entries")
        if any(e.amount.currency != self.currency for e in self.entries):
            raise InvalidTransaction("all entries must share the transaction currency")
        if self.total_debits != self.total_credits:
            raise UnbalancedTransaction(
                f"debits {self.total_debits.cents} differ from credits {self.total_credits.cents}"
            )

    @classmethod
    def post(
        cls,
        *,
        order_id: UUID,
        payment_id: UUID,
        entries: list[Entry],
        created_at: datetime,
        platform_fee: Money,
    ) -> Transaction:
        if not entries:
            raise InvalidTransaction("a transaction needs at least two entries")
        transaction = cls(
            id=uuid4(),
            order_id=order_id,
            payment_id=payment_id,
            currency=entries[0].amount.currency,
            entries=tuple(entries),
            created_at=created_at,
            platform_fee=platform_fee,
        )
        transaction._events.append(
            LedgerTransactionPosted(
                order_id=order_id,
                transaction_id=transaction.id,
                total_cents=transaction.total_debits.cents,
                platform_fee_cents=platform_fee.cents,
            )
        )
        return transaction

    @property
    def total_debits(self) -> Money:
        return self._sum(Direction.DEBIT)

    @property
    def total_credits(self) -> Money:
        return self._sum(Direction.CREDIT)

    def balance_deltas(self) -> dict[Account, int]:
        deltas: dict[Account, int] = {}
        for entry in self.entries:
            deltas[entry.account] = deltas.get(entry.account, 0) + entry.signed_balance_delta
        return dict(sorted(deltas.items(), key=lambda item: item[0].id))

    def pull_events(self) -> list[DomainEvent]:
        events, self._events = self._events, []
        return events

    def _sum(self, direction: Direction) -> Money:
        total = Money.zero(self.currency)
        for entry in self.entries:
            if entry.direction is direction:
                total = total + entry.amount
        return total
