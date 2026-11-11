from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class CatalogProduct:
    id: UUID
    slug: str
    name: str
    description: str
    price_cents: int
    category: str
    rating: float
    reviews_count: int
    tags: tuple[str, ...]
    merchant_name: str


@dataclass(frozen=True)
class ChunkDraft:
    chunk_id: str
    product_id: UUID
    chunk_index: int
    content: str
    content_hash: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class EmbeddedChunk:
    draft: ChunkDraft
    embedding: list[float]


@dataclass(frozen=True)
class Filters:
    max_price_cents: int | None = None
    min_price_cents: int | None = None
    category: str | None = None
    product_ids: tuple[UUID, ...] | None = None
    min_rating: float | None = None

    @property
    def is_empty(self) -> bool:
        return (
            self.max_price_cents is None
            and self.min_price_cents is None
            and self.category is None
            and self.product_ids is None
            and self.min_rating is None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_price_cents": self.max_price_cents,
            "min_price_cents": self.min_price_cents,
            "category": self.category,
            "product_ids": [str(p) for p in self.product_ids] if self.product_ids else None,
            "min_rating": self.min_rating,
        }

    def matches(self, price_cents: int, category: str, rating: float, product_id: UUID) -> bool:
        return (
            (self.max_price_cents is None or price_cents <= self.max_price_cents)
            and (self.min_price_cents is None or price_cents >= self.min_price_cents)
            and (self.category is None or category == self.category)
            and (self.min_rating is None or rating >= self.min_rating)
            and (self.product_ids is None or product_id in self.product_ids)
        )


@dataclass(frozen=True)
class Passage:
    chunk_id: str
    product_id: UUID
    slug: str
    name: str
    category: str
    price_cents: int
    rating: float
    content: str
    score: float = 0.0
    source: str = "hybrid"

    def with_score(self, score: float, source: str) -> Passage:
        return Passage(
            self.chunk_id,
            self.product_id,
            self.slug,
            self.name,
            self.category,
            self.price_cents,
            self.rating,
            self.content,
            score,
            source,
        )


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    result_summary: str
    duration_ms: int
    ok: bool = True


@dataclass(frozen=True)
class Observation:
    tool: str
    arguments: dict[str, Any]
    summary: str
    data: dict[str, Any]
    ok: bool = True


@dataclass(frozen=True)
class Turn:
    role: str
    content: str
    product_ids: tuple[UUID, ...] = ()
    created_at: datetime | None = None
    citations: tuple[dict[str, Any], ...] = ()
    tool_calls: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class Citation:
    product_id: UUID
    slug: str
    name: str
    score: float


@dataclass
class AgentOutcome:
    intent: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    passages: list[Passage] = field(default_factory=list)
