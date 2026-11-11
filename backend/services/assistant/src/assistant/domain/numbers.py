import re
from decimal import Decimal, InvalidOperation

_MARKER = re.compile(r"\[\d+\]")
_SCALE = re.compile(r"\bde\s+5\b")
_NUMBER = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?")


def _to_decimal(raw: str) -> Decimal | None:
    value = raw
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", value):
        value = value.replace(".", "")
    try:
        return Decimal(value).normalize()
    except InvalidOperation:
        return None


_MONEY = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)")


def extract_money(text: str) -> list[Decimal]:
    values = (_to_decimal(m.group(1)) for m in _MONEY.finditer(text))
    return [v for v in values if v is not None]


def extract_numbers(text: str) -> list[Decimal]:
    cleaned = _SCALE.sub(" ", _MARKER.sub(" ", text))
    numbers = (_to_decimal(m.group(0)) for m in _NUMBER.finditer(cleaned))
    return [n for n in numbers if n is not None]
