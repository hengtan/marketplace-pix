from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from catalog.domain.errors import InvalidQuery
from catalog.domain.pagination import PageRequest
from catalog.domain.sorting import SortOrder

MAX_RATING = Decimal("5")
MAX_SEARCH_LENGTH = 100


@dataclass(frozen=True, slots=True)
class Merchant:
    id: UUID
    slug: str
    name: str


@dataclass(frozen=True, slots=True)
class Category:
    slug: str
    label: str
    count: int = 0


@dataclass(frozen=True, slots=True)
class Product:
    id: UUID
    slug: str
    name: str
    description: str
    price_cents: int
    currency: str
    category: str
    image_url: str | None
    rating: Decimal
    reviews_count: int
    tags: tuple[str, ...]
    merchant: Merchant
    created_at: datetime
    active: bool = True

    def __post_init__(self) -> None:
        if self.price_cents <= 0:
            raise ValueError("price_cents must be positive")
        if not Decimal(0) <= self.rating <= MAX_RATING:
            raise ValueError("rating must be between 0 and 5")
        if self.reviews_count < 0:
            raise ValueError("reviews_count cannot be negative")


def normalize_search_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", stripped).strip().lower()


@dataclass(frozen=True, slots=True)
class ProductQuery:
    search: str | None = None
    category: str | None = None
    min_price_cents: int | None = None
    max_price_cents: int | None = None
    sort: SortOrder = SortOrder.RELEVANCE
    page: PageRequest = PageRequest()

    def __post_init__(self) -> None:
        for price in (self.min_price_cents, self.max_price_cents):
            if price is not None and price < 0:
                raise InvalidQuery("price filters cannot be negative")
        if (
            self.min_price_cents is not None
            and self.max_price_cents is not None
            and self.min_price_cents > self.max_price_cents
        ):
            raise InvalidQuery("min_price_cents cannot be greater than max_price_cents")
        if self.search is not None and len(self.search) > MAX_SEARCH_LENGTH:
            raise InvalidQuery(f"q cannot exceed {MAX_SEARCH_LENGTH} characters")

    @property
    def normalized_search(self) -> str | None:
        if self.search is None:
            return None
        text = normalize_search_text(self.search)
        return text or None
