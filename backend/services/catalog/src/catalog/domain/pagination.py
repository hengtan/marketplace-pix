from __future__ import annotations

from dataclasses import dataclass

from catalog.domain.errors import InvalidQuery

DEFAULT_PAGE_SIZE = 12
MAX_PAGE_SIZE = 48


@dataclass(frozen=True, slots=True)
class PageRequest:
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    def __post_init__(self) -> None:
        if self.page < 1:
            raise InvalidQuery("page must be at least 1")
        if not 1 <= self.page_size <= MAX_PAGE_SIZE:
            raise InvalidQuery(f"page_size must be between 1 and {MAX_PAGE_SIZE}")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: list[T]
    total: int
    page: int
    page_size: int
