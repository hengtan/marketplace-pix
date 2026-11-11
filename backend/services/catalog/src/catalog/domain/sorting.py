from __future__ import annotations

from enum import StrEnum


class SortOrder(StrEnum):
    RELEVANCE = "relevance"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    NEWEST = "newest"
    RATING = "rating"
