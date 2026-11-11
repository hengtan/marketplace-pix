from __future__ import annotations

from dataclasses import dataclass

from ledger.domain.errors import InvalidMoney


@dataclass(frozen=True, slots=True)
class Money:
    cents: int
    currency: str = "BRL"

    def __post_init__(self) -> None:
        if not isinstance(self.cents, int) or isinstance(self.cents, bool):
            raise InvalidMoney("cents must be an int")
        if self.cents < 0:
            raise InvalidMoney("money cannot be negative")

    @classmethod
    def zero(cls, currency: str = "BRL") -> Money:
        return cls(0, currency)

    @property
    def is_zero(self) -> bool:
        return self.cents == 0

    def __add__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(self.cents + other.cents, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(self.cents - other.cents, self.currency)

    def times(self, quantity: int) -> Money:
        if quantity < 0:
            raise InvalidMoney("quantity cannot be negative")
        return Money(self.cents * quantity, self.currency)

    def _same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise InvalidMoney("currency mismatch")
