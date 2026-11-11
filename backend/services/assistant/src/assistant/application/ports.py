from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from assistant.domain.models import (
    CatalogProduct,
    EmbeddedChunk,
    Filters,
    Observation,
    Passage,
    Turn,
)


class Embedder(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class ContextItem:
    index: int
    passage: Passage


@dataclass(frozen=True)
class Prompt:
    system: str
    question: str
    context: tuple[ContextItem, ...]
    observations: tuple[Observation, ...]
    text: str
    history: tuple[Turn, ...] = field(default_factory=tuple)
    intent: str | None = None


class LlmClient(Protocol):
    @property
    def name(self) -> str: ...

    async def generate(self, prompt: Prompt) -> str: ...

    def stream(self, prompt: Prompt) -> AsyncIterator[str]: ...


class Reranker(Protocol):
    def rerank(
        self,
        query: str,
        candidates: Sequence[Passage],
        limit: int,
        extra_terms: Sequence[str] = (),
    ) -> list[Passage]: ...


@dataclass(frozen=True)
class Action:
    tool: str
    arguments: dict[str, Any]


class Planner(Protocol):
    async def next_action(
        self,
        message: str,
        history: Sequence[Turn],
        observations: Sequence[Observation],
        intent: str | None = None,
    ) -> Action | None: ...


@dataclass(frozen=True)
class ToolResult:
    summary: str
    data: dict[str, Any]
    passages: tuple[Passage, ...] = ()
    ok: bool = True


class Tool(Protocol):
    name: str

    async def run(self, arguments: dict[str, Any]) -> ToolResult: ...


class ChunkStore(Protocol):
    async def existing_hashes(self) -> dict[str, str]: ...

    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None: ...

    async def delete(self, chunk_ids: Sequence[str]) -> None: ...

    async def vector_search(
        self, embedding: Sequence[float], embedder: str, filters: Filters, limit: int
    ) -> list[Passage]: ...

    async def text_search(
        self, query: str, embedder: str, filters: Filters, limit: int
    ) -> list[Passage]: ...

    async def browse(
        self, embedder: str, filters: Filters, sort: str | None, limit: int
    ) -> list[Passage]: ...

    async def categories(self, embedder: str) -> dict[str, str]: ...

    async def product_chunks(
        self, embedder: str, product_ids: Sequence[UUID] | None = None
    ) -> dict[UUID, list[str]]: ...

    async def embeddings(self, chunk_ids: Sequence[str]) -> dict[str, list[float]]: ...

    async def product_names(self, embedder: str) -> list[str]: ...


class CatalogGateway(Protocol):
    async def list_products(self) -> list[CatalogProduct]: ...

    async def get_product(self, product_id: UUID) -> CatalogProduct | None: ...

    async def categories(self) -> dict[str, str]: ...


@dataclass(frozen=True)
class StockInfo:
    product_id: UUID
    available: int
    reserved: int


class InventoryGateway(Protocol):
    async def get_stock(self, product_id: UUID) -> StockInfo | None: ...


@dataclass(frozen=True)
class OrderInfo:
    order_id: UUID
    status: str
    total_cents: int
    currency: str
    items_count: int
    created_at: str
    cancel_reason: str | None


class OrderGateway(Protocol):
    async def get_order(self, order_id: UUID) -> OrderInfo | None: ...


@dataclass(frozen=True)
class StoredMessage:
    role: str
    content: str
    created_at: datetime
    meta: dict[str, Any]


class SessionStore(Protocol):
    async def ensure(self, session_id: UUID) -> datetime: ...

    async def created_at(self, session_id: UUID) -> datetime | None: ...

    async def append(
        self, session_id: UUID, role: str, content: str, meta: dict[str, Any]
    ) -> None: ...

    async def messages(self, session_id: UUID, limit: int | None = None) -> list[StoredMessage]: ...


@dataclass(frozen=True)
class EvalRunRecord:
    run_id: UUID
    created_at: datetime
    passed: bool
    metrics: dict[str, Any]
    thresholds: dict[str, Any]
    cases: list[dict[str, Any]]
    embedder: str
    llm: str


class EvalStore(Protocol):
    async def save(self, record: EvalRunRecord) -> None: ...

    async def latest(self) -> EvalRunRecord | None: ...
