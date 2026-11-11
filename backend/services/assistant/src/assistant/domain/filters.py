import re
from collections.abc import Mapping
from dataclasses import dataclass

from assistant.domain.models import Filters
from assistant.domain.text import normalize

_NUMBER = r"(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_MAX_PRICE = re.compile(
    rf"\b(?:ate|menos de|abaixo de|no maximo|maximo de|nao passe de|ate o valor de)\s*"
    rf"(?:r\$\s*)?{_NUMBER}(?:\s*(?:reais|real))?"
)
_MIN_PRICE = re.compile(
    rf"\b(?:acima de|mais de|a partir de|no minimo|minimo de)\s*(?:r\$\s*)?{_NUMBER}"
    rf"(?:\s*(?:reais|real))?"
)
_CATEGORY_STOP = frozenset({"e", "de", "da", "do", "para", "com"})
_SORT_PRICE = re.compile(r"\b(?:mais barat\w*|menor(?:es)? preco\w*|mais em conta)\b")
_SORT_RATING = re.compile(
    r"\b(?:mais bem avaliad\w*|melhor(?:es)? avaliad\w*|melhor(?:es)? avaliac\w*"
    r"|melhor nota|maior nota)\b"
)


@dataclass(frozen=True)
class ParsedQuery:
    filters: Filters
    text: str
    sort: str | None = None


def _to_cents(raw: str) -> int:
    value = raw.strip()
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", value):
        value = value.replace(".", "")
    return round(float(value) * 100)


def _singular(word: str) -> str:
    return word[:-1] if len(word) > 4 and word.endswith("s") else word


def _category_words(slug: str, label: str) -> set[str]:
    words = {normalize(slug)}
    for raw in normalize(label).split():
        if len(raw) > 3 and raw not in _CATEGORY_STOP:
            words.add(raw)
    return words


class FilterParser:
    """Extracts structured filters (price ceiling/floor, category) from a free-text question
    and returns the question with the matched price phrases removed."""

    def __init__(self, categories: Mapping[str, str]) -> None:
        self._categories = dict(categories)

    def parse(self, question: str) -> ParsedQuery:
        text = normalize(question)
        max_price: int | None = None
        min_price: int | None = None

        match = _MAX_PRICE.search(text)
        if match:
            max_price = _to_cents(match.group(1))
            text = text.replace(match.group(0), " ")
        match = _MIN_PRICE.search(text)
        if match:
            min_price = _to_cents(match.group(1))
            text = text.replace(match.group(0), " ")

        sort: str | None = None
        for pattern, name in ((_SORT_PRICE, "price_asc"), (_SORT_RATING, "rating_desc")):
            found = pattern.search(text)
            if found:
                sort = sort or name
                text = text.replace(found.group(0), " ")

        category, text = self._match_category(text)
        return ParsedQuery(
            Filters(max_price_cents=max_price, min_price_cents=min_price, category=category),
            " ".join(text.split()),
            sort,
        )

    def _match_category(self, text: str) -> tuple[str | None, str]:
        words = re.findall(r"[a-z0-9]+", text)
        for slug, label in self._categories.items():
            keys = _category_words(slug, label)
            hits = [w for w in words if w in keys or _singular(w) in keys]
            if hits:
                remaining = [w for w in words if w not in hits]
                return slug, " ".join(remaining)
        return None, text
