from __future__ import annotations

from notifications.domain.errors import InvalidMoney


def format_brl(cents: int) -> str:
    if isinstance(cents, bool) or not isinstance(cents, int):
        raise InvalidMoney("cents must be an int")
    sign = "-" if cents < 0 else ""
    reais, centavos = divmod(abs(cents), 100)
    grouped = f"{reais:,}".replace(",", ".")
    return f"{sign}R$ {grouped},{centavos:02d}"
